"""
Deepgram streaming Speech-to-Text client.

Handles real-time transcription of phone audio via Deepgram WebSocket.
"""

import asyncio
import json
import logging
from typing import Callable
from django.conf import settings

try:
    from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
except ImportError:
    # Fallback for older deepgram-sdk versions
    DeepgramClient = None

logger = logging.getLogger(__name__)


class DeepgramSTT:
    """
    Wraps Deepgram's real-time streaming STT in a simple interface.

    Usage:
        stt = DeepgramSTT(on_transcript=my_callback)
        await stt.connect()
        await stt.send_audio(audio_bytes)
        await stt.close()
    """

    def __init__(self, on_transcript: Callable[[str], None]):
        """
        Args:
            on_transcript: Called with the final transcript string
                           when the customer finishes speaking.
        """
        self.on_transcript = on_transcript
        self.dg_client = None
        self.dg_connection = None
        self._transcript_buffer = ''
        self._loop = None

    async def connect(self):
        """Open the Deepgram WebSocket connection."""
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

        await self.dg_connection.start(options)
        logger.info('Deepgram STT connected')

    async def send_audio(self, audio_bytes: bytes):
        """Send raw audio chunk to Deepgram for transcription."""
        if self.dg_connection:
            await self.dg_connection.send(audio_bytes)

    async def close(self):
        """Close the Deepgram connection."""
        if self.dg_connection:
            await self.dg_connection.finish()
            logger.info('Deepgram STT closed')

    async def _on_transcript(self, result, **kwargs):
        """Handle transcript results from Deepgram."""
        try:
            sentence = result.channel.alternatives[0].transcript
            is_final = result.speech_final if hasattr(result, 'speech_final') else not result.is_final

            if sentence and is_final:
                sentence = sentence.strip()
                logger.info(f'STT final: "{sentence}"')
                if self.on_transcript:
                    # Run callback in a thread to not block the event loop
                    await self._loop.run_in_executor(None, self.on_transcript, sentence)

        except Exception as e:
            logger.error(f'STT transcript handler error: {e}')

    def _on_error(self, error, **kwargs):
        logger.error(f'Deepgram error: {error}')

    def _on_close(self, **kwargs):
        logger.info('Deepgram connection closed')
