"""
Deepgram streaming Speech-to-Text client.

Handles real-time transcription of phone audio via Deepgram WebSocket.
"""

import asyncio
import json
import logging
import time
from typing import Callable
from django.conf import settings

try:
    from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
except ImportError:
    # Fallback for older deepgram-sdk versions
    DeepgramClient = None

logger = logging.getLogger(__name__)

# Mu-law silence byte (0xFF = zero level in mu-law)
MULAW_SILENCE_BYTE = b'\xff'


class DeepgramSTT:
    """
    Wraps Deepgram's real-time streaming STT in a simple interface.

    Usage:
        stt = DeepgramSTT(on_transcript=my_callback)
        await stt.connect()
        stt.send_audio(audio_bytes)  # sync call — v3 SDK
        await stt.close()
    """

    def __init__(self, on_transcript: Callable[[str], None], keepalive_interval: float = 5.0):
        """
        Args:
            on_transcript: Called with the final transcript string
                           when the customer finishes speaking.
            keepalive_interval: Seconds between keepalive silence frames
                                (default 5s — Deepgram idle timeout is ~10s).
        """
        self.on_transcript = on_transcript
        self.dg_client = None
        self.dg_connection = None
        self._transcript_buffer = ''
        self._loop = None
        self._keepalive_interval = keepalive_interval
        self._keepalive_task = None
        self._last_audio_sent = 0.0  # monotonic timestamp of last send

    async def connect(self):
        """Open the Deepgram WebSocket connection and start keepalive."""
        self._loop = asyncio.get_event_loop()
        api_key = settings.DEEPGRAM_API_KEY

        self.dg_client = DeepgramClient(api_key)
        self.dg_connection = self.dg_client.listen.websocket.v('1')

        # Register event handlers
        self.dg_connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
        self.dg_connection.on(LiveTranscriptionEvents.Error, self._on_error)
        self.dg_connection.on(LiveTranscriptionEvents.Close, self._on_close)

        # Configure for phone call audio (8kHz mulaw is Twilio's format)
        options = LiveOptions(
            model='nova-2-phonecall',
            language='en-US',
            encoding='mulaw',
            sample_rate=8000,
            channels=1,
            interim_results=True,
            endpointing=500,  # ms of silence before finalizing
            smart_format=True,
        )

        self.dg_connection.start(options)
        self._last_audio_sent = time.monotonic()
        logger.info('Deepgram STT connected')

        # Start keepalive to prevent Deepgram idle timeout (~10s)
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _keepalive_loop(self):
        """
        Send KeepAlive text messages to prevent Deepgram idle timeout (~10s).
        Uses JSON KeepAlive (not audio) so Deepgram doesn't try to transcribe it.
        """
        try:
            while self.dg_connection:
                await asyncio.sleep(self._keepalive_interval)
                elapsed = time.monotonic() - self._last_audio_sent
                if elapsed >= self._keepalive_interval:
                    # No real audio sent recently — push a KeepAlive text message
                    try:
                        self.dg_connection.send(json.dumps({"type": "KeepAlive"}))
                    except Exception:
                        pass  # Connection may already be closed
        except asyncio.CancelledError:
            pass

    def send_audio(self, audio_bytes: bytes):
        """Send raw audio chunk to Deepgram for transcription (sync — v3 SDK send is not async)."""
        if self.dg_connection:
            self._last_audio_sent = time.monotonic()
            self.dg_connection.send(audio_bytes)

    async def close(self):
        """Close the Deepgram connection and cancel keepalive."""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self.dg_connection:
            self.dg_connection.finish()
            logger.info('Deepgram STT closed')

    def _on_transcript(self, client, result, **kwargs):
        """Handle transcript results from Deepgram (v3 sync callback)."""
        try:
            sentence = result.channel.alternatives[0].transcript
            is_final = result.speech_final if hasattr(result, 'speech_final') else not result.is_final

            if sentence and is_final:
                sentence = sentence.strip()
                logger.info(f'STT final: "{sentence}"')
                if self.on_transcript:
                    self.on_transcript(sentence)
            elif sentence and not is_final:
                # Log interim results periodically to confirm audio is flowing
                if not hasattr(self, '_interim_count'):
                    self._interim_count = 0
                self._interim_count += 1
                if self._interim_count % 50 == 1:
                    logger.info(f'🎤 Interim: "{sentence}"')

        except Exception as e:
            logger.error(f'STT transcript handler error: {e}')

    def _on_error(self, *args, **kwargs):
        logger.error(f'Deepgram error: {args}')

    def _on_close(self, *args, **kwargs):
        logger.info('Deepgram connection closed')
