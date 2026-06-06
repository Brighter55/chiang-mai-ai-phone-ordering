"""
Text-to-Speech abstraction.

Phase 1: Uses Twilio's built-in <Say> (free, robotic but functional).
Phase 2: Upgrade path to Deepgram Aura or ElevenLabs for natural voice.

Both implement: text -> audio_bytes (or TwiML for Twilio)
"""

import logging

logger = logging.getLogger(__name__)


def text_to_twiml_say(text: str) -> str:
    """
    Convert text to Twilio <Say> TwiML.
    This is the simplest/free approach — Twilio reads the text with its built-in TTS.

    Returns a TwiML string that can be sent back to Twilio.
    """
    # Escape XML special chars
    safe_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="Polly.Joanna">{safe_text}</Say></Response>'


def text_to_media_stream_audio(text: str) -> bytes:
    """
    Placeholder: Convert text to raw audio bytes for sending over Media Streams.

    For Phase 2: integrate Deepgram Aura TTS or ElevenLabs here.
    For Phase 1: we use Twilio <Say> via a separate mechanism (see consumer).
    """
    # TODO: Integrate Deepgram Aura TTS
    # import httpx
    # async with httpx.AsyncClient() as client:
    #     r = await client.post('https://api.deepgram.com/v1/speak', ...)

    raise NotImplementedError(
        'Direct audio TTS not yet implemented. Use text_to_twiml_say() instead.'
    )
