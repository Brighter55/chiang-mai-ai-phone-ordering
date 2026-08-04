"""
Django Channels WebSocket consumer — the core audio pipeline.

Receives audio from Twilio Media Streams, pipes it through:
    Twilio audio → Deepgram STT → OpenAI → Deepgram TTS → Twilio audio
When the order is finalized, saves to DB and sends SMS.
"""

import asyncio
import base64
import json
import logging
import time
import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer

from .agent import OrderAgent, build_keyterms, save_order_from_agent, strip_order_json
from .stt import DeepgramSTT
from .notify import send_order_sms, get_twilio_client

logger = logging.getLogger(__name__)


class CallConsumer(AsyncWebsocketConsumer):
    """
    Handles one phone call from start to finish.

    Lifecycle:
        connect → receive (loop) → disconnect
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_sid = ''
        self.caller_phone = ''
        self.agent = None          # OrderAgent (OpenAI)
        self.stt = None            # DeepgramSTT
        self.dg_tts_ws = None      # Deepgram TTS WebSocket
        self.stream_sid = None     # Twilio Media Stream identifier
        self.stream_ready = asyncio.Event()  # Signaled when Twilio stream starts
        self.transcript_queue = asyncio.Queue()  # Queue for transcripts to process
        self.is_speaking = False   # True while TTS audio is playing
        self.order_saved = False
        self._media_count = 0      # Counter for audio packets forwarded
        # Barge-in detection
        self._barge_in_buffer = []       # Recent audio energy samples during speech
        self._barge_in_audio = []        # Buffered audio packets during speech (for barge-in replay)
        self._barge_in_triggered = False # True when customer interrupts AI
        self._barge_in_cooldown_until = 0.0  # monotonic timestamp — no barge-in until after this
        self._barge_in_enabled = False   # Disabled by default — echo makes it unreliable on phone calls
        self.greeting_done = asyncio.Event()  # Set when the greeting TTS finishes
        # Timing instrumentation
        self._timings = {}         # Stage → list of durations

    async def connect(self):
        """Accept the WebSocket from Twilio and set up the AI pipeline."""
        await self.accept()
        logger.info('Call WebSocket connected')

        # Initialize the AI agent (DB queries need sync_to_async in Channels)
        self.agent = await sync_to_async(OrderAgent, thread_sensitive=False)()

        # Start STT immediately so we don't miss early speech.
        # Transcripts during greeting are filtered via is_speaking flag.
        # The keepalive prevents Deepgram's idle timeout during the greeting.
        self.stt = DeepgramSTT(on_transcript=self._on_transcript,
                               keyterms=build_keyterms(self.agent.menu_items))
        await self.stt.connect()
        logger.info('Deepgram STT started (before greeting)')

        # Start processing transcripts from the queue
        asyncio.create_task(self._process_transcripts())

        # Greet the customer — STT is already running and will catch early speech
        asyncio.create_task(self._greet())

    async def disconnect(self, close_code):
        """Call ended — clean up and log timing summary."""
        logger.info(f'Call WebSocket disconnected (code: {close_code})')

        # Log timing summary for the call
        if self._timings:
            summary = {}
            for stage, durations in self._timings.items():
                if durations:
                    avg = sum(durations) / len(durations)
                    summary[stage] = f'avg={avg:.3f}s n={len(durations)}'
            logger.info(f'⏱ Timing summary: {summary}')

        # Clean up STT
        if self.stt:
            await self.stt.close()

        # Close TTS WebSocket if open
        if self.dg_tts_ws:
            await self.dg_tts_ws.close()

    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle messages from Twilio Media Streams.
        Two types: 'media' (audio chunks) and control messages.
        """
        if text_data:
            msg = json.loads(text_data)
            event = msg.get('event', '')

            if event == 'media':
                # Track stream_sid
                if not self.stream_sid:
                    self.stream_sid = msg.get('streamSid', '')

                payload = msg['media']['payload']
                audio_bytes = base64.b64decode(payload)

                # Audio chunk from Twilio — forward to Deepgram STT
                if not self.is_speaking and self.stt:
                    self.stt.send_audio(audio_bytes)
                    self._media_count += 1
                    if self._media_count % 250 == 1:  # Log every ~5s (50 packets/s)
                        logger.info(f'🎙 Audio streaming: {self._media_count} packets forwarded')
                elif self.is_speaking:
                    if self._barge_in_enabled:
                        # AI is speaking — buffer audio for potential barge-in detection
                        energy = self._mulaw_energy(audio_bytes)

                        # Keep a rolling buffer of audio packets for replay on barge-in
                        self._barge_in_audio.append(audio_bytes)
                        if len(self._barge_in_audio) > 30:  # ~600ms window
                            self._barge_in_audio.pop(0)

                        # Track energy for barge-in detection
                        self._barge_in_buffer.append(energy)
                        if len(self._barge_in_buffer) > 15:  # ~300ms window
                            self._barge_in_buffer.pop(0)

                        # Trigger barge-in if last 10 consecutive packets (~200ms) show sustained speech.
                        # Higher threshold + cooldown prevents echo from creating an infinite loop.
                        now = time.monotonic()
                        if (len(self._barge_in_buffer) >= 10
                                and all(e > 0.25 for e in self._barge_in_buffer[-10:])
                                and now >= self._barge_in_cooldown_until):
                            if not self._barge_in_triggered:
                                asyncio.create_task(self._handle_barge_in())
                        elif not hasattr(self, '_dropped_during_speech'):
                            self._dropped_during_speech = 0
                        self._dropped_during_speech += 1
                        if self._dropped_during_speech == 1:
                            logger.info('🔇 AI speaking — monitoring for barge-in')
                    else:
                        # Barge-in disabled — silently drop audio during AI speech (original behavior)
                        if not hasattr(self, '_dropped_during_speech'):
                            self._dropped_during_speech = 0
                        self._dropped_during_speech += 1
                        if self._dropped_during_speech == 1:
                            logger.info('🔇 AI speaking — dropping audio (barge-in disabled)')
                elif not self.stt:
                    if not hasattr(self, '_dropped_before_stt'):
                        self._dropped_before_stt = 0
                    self._dropped_before_stt += 1
                    if self._dropped_before_stt == 1:
                        logger.info('⏳ Audio arriving before STT ready')

            elif event == 'start':
                # Stream starting — extract call metadata
                start_data = msg.get('start', {})
                self.call_sid = start_data.get('callSid', '')
                self.stream_sid = msg.get('streamSid', '')
                # Custom parameters passed from TwiML
                custom_params = start_data.get('customParameters', {})
                self.caller_phone = custom_params.get('caller_phone', '')
                logger.info(f'Stream started — call: {self.call_sid}, from: {self.caller_phone}')
                self.stream_ready.set()

            elif event == 'stop':
                logger.info('Stream stopped by Twilio')
                await self.stt.close()

    async def _greet(self):
        """Wait for Twilio stream to start, then speak greeting.

        STT is already connected before the greeting (see connect()),
        so any early customer speech during/after the greeting is captured.
        Transcripts received while is_speaking=True are discarded.
        """
        try:
            await asyncio.wait_for(self.stream_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error('Stream never started, skipping greeting')
            return

        restaurant = getattr(settings, 'RESTAURANT_NAME', 'Our Restaurant')
        greeting = f"Thank you for calling {restaurant}. All our staff are currently busy assisting other customers, but I can take your order right away. What can I get for you today?"
        await self._speak_response(greeting)
        self.greeting_done.set()
        logger.info('Greeting completed, ready for customer speech')

    def _on_transcript(self, transcript: str):
        """
        Callback from DeepgramSTT — called when customer finishes speaking.
        Queues the transcript for async processing.
        Discards transcripts received while the AI is speaking (echo / false triggers).
        """
        if transcript and not self.is_speaking:
            self.transcript_queue.put_nowait(transcript)

    @staticmethod
    def _mulaw_energy(audio_bytes: bytes) -> float:
        """
        Compute a simple speech-energy metric from mu-law audio.
        Returns 0.0 (all silence) to 1.0 (all loud speech).
        Mu-law silence is 0xFF; values far from 0xFF indicate louder audio.
        """
        if not audio_bytes:
            return 0.0
        non_silent = sum(1 for b in audio_bytes if abs(b - 0xFF) > 6)
        return non_silent / len(audio_bytes)

    async def _handle_barge_in(self):
        """
        Handle customer interrupting the AI while it's speaking.

        Closes the TTS WebSocket to stop audio generation, sends a 'clear'
        event to Twilio to flush its playback buffer, then replays the
        buffered interruption audio into STT so the customer's words are
        captured rather than lost.
        """
        if self._barge_in_triggered:
            return  # Already handling a barge-in
        self._barge_in_triggered = True
        logger.info('🗣 Barge-in detected — stopping TTS')

        # Close TTS WebSocket to stop audio generation
        if self.dg_tts_ws:
            try:
                await self.dg_tts_ws.close()
            except Exception:
                pass
            self.dg_tts_ws = None

        # Clear Twilio's playback buffer so the customer hears silence immediately
        try:
            await self.send(text_data=json.dumps({
                'event': 'clear',
                'streamSid': self.stream_sid,
            }))
        except Exception:
            pass

        self.is_speaking = False

        # Replay buffered audio (the interruption speech) to STT
        if self.stt and self._barge_in_audio:
            logger.info(f'📦 Replaying {len(self._barge_in_audio)} buffered packets to STT')
            for audio_chunk in self._barge_in_audio:
                self.stt.send_audio(audio_chunk)
                self._media_count += 1

        self._barge_in_audio.clear()
        self._barge_in_buffer.clear()

        # Set a 2-second cooldown to prevent echo from triggering another barge-in
        self._barge_in_cooldown_until = time.monotonic() + 2.0

    async def _process_transcripts(self):
        """
        Background task: process queued transcripts through AI and TTS.

        If no transcript arrives within NUDGE_TIMEOUT seconds, the AI nudges
        the customer (instead of staying silent forever). After MAX_NUDGES
        unanswered nudges, says goodbye and hangs up.
        """
        NUDGE_TIMEOUT = 8.0   # Seconds of silence before nudging
        MAX_NUDGES = 2        # Number of nudges before hanging up
        nudge_count = 0

        # Wait for greeting to finish before starting the silence timer
        await self.greeting_done.wait()

        while True:
            try:
                transcript = await asyncio.wait_for(
                    self.transcript_queue.get(),
                    timeout=NUDGE_TIMEOUT,
                )
                nudge_count = 0  # Reset — customer is speaking
                turn_start = time.monotonic()

                # Send to AI for a response
                ai_start = time.monotonic()
                response_text = await self.agent.process_transcript(transcript)
                ai_elapsed = time.monotonic() - ai_start
                logger.info(f'AI response ({ai_elapsed:.3f}s): {response_text[:100]}...')
                self._timings.setdefault('openai', []).append(ai_elapsed)

                # Strip order JSON before TTS so it's not spoken aloud
                spoken_text = strip_order_json(response_text)
                await self._speak_response(spoken_text)

                # Check if order was finalized
                if self.agent.is_order_complete and not self.order_saved:
                    self.order_saved = True
                    await self._finalize_order()
                    # Hang up the call after a brief pause for the goodbye audio
                    await asyncio.sleep(0.5)
                    await self._hangup_call()

                turn_total = time.monotonic() - turn_start
                logger.info(f'⏱ Turn total: {turn_total:.3f}s (AI: {ai_elapsed:.3f}s)')
                self._timings.setdefault('turn_total', []).append(turn_total)

            except asyncio.TimeoutError:
                nudge_count += 1
                if nudge_count > MAX_NUDGES:
                    logger.info('Max nudges reached — hanging up')
                    await self._speak_response(
                        "I'm sorry, I'm having trouble hearing you. "
                        "Please call back and try again. Goodbye!"
                    )
                    await asyncio.sleep(0.5)
                    await self._hangup_call()
                    break
                logger.info(f'Nudge #{nudge_count} — no transcript for {NUDGE_TIMEOUT}s')
                await self._speak_response(
                    "I'm sorry, I didn't catch that. Could you repeat?"
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Transcript processing error: {e}')

    async def _speak_response(self, text: str):
        """
        Convert text to speech and send audio back to Twilio.
        Uses Deepgram Aura TTS HTTP API (reliable) with frame-by-frame streaming.
        """
        self.is_speaking = True
        self._barge_in_triggered = False
        self._barge_in_buffer.clear()
        self._barge_in_audio.clear()

        tts_start = time.monotonic()
        try:
            dg_api_key = settings.DEEPGRAM_API_KEY
            url = f'https://api.deepgram.com/v1/speak?model={settings.DEEPGRAM_TTS_MODEL}&encoding=mulaw&sample_rate=8000&rate={settings.DEEPGRAM_TTS_RATE}'

            headers = {
                'Authorization': f'Token {dg_api_key}',
                'Content-Type': 'application/json',
            }
            payload = {'text': text}

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, json=payload)

                if response.status_code == 200:
                    audio_bytes = response.content
                    tts_fetch = time.monotonic() - tts_start
                    logger.info(f'⏱ TTS fetched: {tts_fetch:.3f}s ({len(audio_bytes)} bytes)')
                    self._timings.setdefault('tts_total', []).append(tts_fetch)

                    # Stream audio to Twilio in 20ms frames
                    chunk_size = 160  # 8kHz mulaw = 8000 bytes/sec = 160 bytes per 20ms
                    for i in range(0, len(audio_bytes), chunk_size):
                        chunk = audio_bytes[i:i + chunk_size]
                        payload = base64.b64encode(chunk).decode('utf-8')
                        await self.send(text_data=json.dumps({
                            'event': 'media',
                            'streamSid': self.stream_sid,
                            'media': {'payload': payload},
                        }))
                        await asyncio.sleep(0.02)  # 20ms pacing

                    # Short pause after speaking before re-enabling listening
                    await asyncio.sleep(0.15)
                else:
                    logger.error(f'TTS API error: {response.status_code} {response.text[:200]}')

        except Exception as e:
            logger.error(f'TTS error: {e}')

        finally:
            self.is_speaking = False

    async def _finalize_order(self):
        """
        Save the completed order to the database and send SMS to restaurant.
        Runs the entire save+sms pipeline in a sync thread to avoid
        SynchronousOnlyOperation from Django ORM.
        """
        def _save_and_notify():
            order = save_order_from_agent(self.agent, call_sid=self.call_sid)
            if order:
                sms_sid = send_order_sms(order)
                return order.id, sms_sid
            return None, None

        try:
            order_id, sms_sid = await sync_to_async(
                _save_and_notify, thread_sensitive=False
            )()
            if order_id:
                logger.info(f'Order #{order_id} saved and SMS sent: {sms_sid}')
            else:
                logger.error('Failed to save order from agent data')
        except Exception as e:
            logger.error(f'Order finalization error: {e}')

    async def _hangup_call(self):
        """
        Hang up the Twilio call via REST API.
        Runs synchronously in a thread to avoid blocking the event loop.
        """
        def _hangup():
            client = get_twilio_client()
            try:
                client.calls(self.call_sid).update(status='completed')
                logger.info(f'Call {self.call_sid} hung up successfully')
                return True
            except Exception as e:
                logger.error(f'Failed to hang up call {self.call_sid}: {e}')
                return False

        if self.call_sid:
            await sync_to_async(_hangup, thread_sensitive=False)()
            # Close the WebSocket so Twilio stops the media stream
            await self.close()
        else:
            logger.warning('No call_sid to hang up')
