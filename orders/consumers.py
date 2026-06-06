"""
Django Channels WebSocket consumer — the core audio pipeline.

Receives audio from Twilio Media Streams, pipes it through:
    Twilio audio → Deepgram STT → Claude Haiku → Deepgram TTS → Twilio audio
When the order is finalized, saves to DB and sends SMS.
"""

import asyncio
import base64
import json
import logging
import os
import httpx
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
        self.agent = None          # OrderAgent (Claude Haiku)
        self.stt = None            # DeepgramSTT
        self.dg_tts_ws = None      # Deepgram TTS WebSocket
        self.stream_sid = None     # Twilio Media Stream identifier
        self.transcript_queue = asyncio.Queue()  # Queue for transcripts to process
        self.is_speaking = False   # True while TTS audio is playing
        self.order_saved = False

    async def connect(self):
        """Accept the WebSocket from Twilio and set up the AI pipeline."""
        await self.accept()
        logger.info('Call WebSocket connected')

        # Initialize the Claude agent
        self.agent = OrderAgent()

        # Set up STT with a callback that queues transcripts
        self.stt = DeepgramSTT(on_transcript=self._on_transcript)
        await self.stt.connect()

        # Start processing transcripts from the queue
        asyncio.create_task(self._process_transcripts())

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
                # Audio chunk from Twilio — forward to Deepgram STT
                if not self.is_speaking:  # Don't transcribe while we're talking
                    payload = msg['media']['payload']
                    audio_bytes = base64.b64decode(payload)
                    await self.stt.send_audio(audio_bytes)

                # Track stream_sid
                if not self.stream_sid:
                    self.stream_sid = msg.get('streamSid', '')

            elif event == 'start':
                # Stream starting — extract call metadata
                start_data = msg.get('start', {})
                self.call_sid = start_data.get('callSid', '')
                self.stream_sid = msg.get('streamSid', '')
                # Custom parameters passed from TwiML
                custom_params = start_data.get('customParameters', {})
                self.caller_phone = custom_params.get('caller_phone', '')
                logger.info(f'Stream started — call: {self.call_sid}, from: {self.caller_phone}')

            elif event == 'stop':
                logger.info('Stream stopped by Twilio')
                await self.stt.close()

    def _on_transcript(self, transcript: str):
        """
        Callback from DeepgramSTT — called when customer finishes speaking.
        Queues the transcript for async processing.
        """
        if transcript:
            self.transcript_queue.put_nowait(transcript)

    async def _process_transcripts(self):
        """
        Background task: process queued transcripts through Claude and TTS.
        """
        while True:
            try:
                transcript = await self.transcript_queue.get()

                # Send to Claude for a response
                response_text = await self.agent.process_transcript(transcript)
                logger.info(f'Claude response: {response_text[:100]}...')

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
        """
        try:
            order = save_order_from_agent(self.agent, call_sid=self.call_sid)
            if order:
                sms_sid = send_order_sms(order)
                logger.info(f'Order #{order.id} saved and SMS sent: {sms_sid}')
            else:
                logger.error('Failed to save order from agent data')
        except Exception as e:
            logger.error(f'Order finalization error: {e}')
