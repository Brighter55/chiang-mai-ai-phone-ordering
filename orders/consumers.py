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
import os
import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer

from .agent import OrderAgent, save_order_from_agent
from .stt import DeepgramSTT
from .notify import send_order_sms

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

    async def connect(self):
        """Accept the WebSocket from Twilio and set up the AI pipeline."""
        await self.accept()
        logger.info('Call WebSocket connected')

        # Initialize the AI agent (DB queries need sync_to_async in Channels)
        self.agent = await sync_to_async(OrderAgent, thread_sensitive=False)()

        # Start processing transcripts from the queue
        asyncio.create_task(self._process_transcripts())

        # Greet the customer first, then start STT (avoids Deepgram idle timeout)
        asyncio.create_task(self._greet())

    async def disconnect(self, close_code):
        """Call ended — clean up and save any partial order."""
        logger.info(f'Call WebSocket disconnected (code: {close_code})')

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

                # Audio chunk from Twilio — forward to Deepgram STT
                if not self.is_speaking and self.stt:
                    payload = msg['media']['payload']
                    audio_bytes = base64.b64decode(payload)
                    self.stt.send_audio(audio_bytes)
                    self._media_count += 1
                    if self._media_count % 250 == 1:  # Log every ~5s (50 packets/s)
                        logger.info(f'🎙 Audio streaming: {self._media_count} packets forwarded')
                elif self.is_speaking:
                    if not hasattr(self, '_dropped_during_speech'):
                        self._dropped_during_speech = 0
                    self._dropped_during_speech += 1
                    if self._dropped_during_speech == 1:
                        logger.info('🔇 Dropping audio during greeting (expected)')
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
        """Wait for Twilio stream to start, speak greeting, then start STT."""
        try:
            await asyncio.wait_for(self.stream_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error('Stream never started, skipping greeting')
            return

        restaurant = getattr(settings, 'RESTAURANT_NAME', 'Our Restaurant')
        greeting = f"Thank you for calling {restaurant}, this is AI order assistant. What can I get for you today?"
        await self._speak_response(greeting)

        # Now that the greeting is done, start STT so Deepgram doesn't idle timeout
        self.stt = DeepgramSTT(on_transcript=self._on_transcript)
        await self.stt.connect()
        logger.info('Deepgram STT started after greeting')

    def _on_transcript(self, transcript: str):
        """
        Callback from DeepgramSTT — called when customer finishes speaking.
        Queues the transcript for async processing.
        """
        if transcript:
            self.transcript_queue.put_nowait(transcript)

    async def _process_transcripts(self):
        """
        Background task: process queued transcripts through AI and TTS.
        """
        while True:
            try:
                transcript = await self.transcript_queue.get()

                # Send to AI for a response
                response_text = await self.agent.process_transcript(transcript)
                logger.info(f'AI response: {response_text[:100]}...')

                # Speak the response
                await self._speak_response(response_text)

                # Check if order was finalized
                if self.agent.is_order_complete and not self.order_saved:
                    self.order_saved = True
                    await self._finalize_order()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Transcript processing error: {e}')

    async def _speak_response(self, text: str):
        """
        Convert text to speech and send audio back to Twilio.
        Uses Deepgram Aura TTS for natural voice, streaming to reduce latency.
        """
        self.is_speaking = True

        try:
            dg_api_key = settings.DEEPGRAM_API_KEY
            url = 'https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mulaw&sample_rate=8000'

            headers = {
                'Authorization': f'Token {dg_api_key}',
                'Content-Type': 'application/json',
            }
            payload = {'text': text}

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=payload)

                if response.status_code == 200:
                    audio_bytes = response.content
                    # Send audio back to Twilio in chunks (Twilio wants 20ms frames for mulaw)
                    # 8kHz mulaw = 8000 bytes/sec = 160 bytes per 20ms frame
                    chunk_size = 160
                    for i in range(0, len(audio_bytes), chunk_size):
                        chunk = audio_bytes[i:i + chunk_size]
                        payload = base64.b64encode(chunk).decode('utf-8')
                        media_msg = {
                            'event': 'media',
                            'streamSid': self.stream_sid,
                            'media': {'payload': payload},
                        }
                        await self.send(text_data=json.dumps(media_msg))
                        await asyncio.sleep(0.02)  # 20ms pacing

                    # Small pause after speaking
                    await asyncio.sleep(0.3)
                else:
                    logger.error(f'TTS API error: {response.status_code} {response.text}')

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
