"""
Twilio webhook views — handle incoming calls and SMS status callbacks.
"""

import logging
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def twilio_voice_webhook(request):
    """
    Called by Twilio when a customer calls your Twilio number.
    Returns TwiML that connects the call to our WebSocket audio stream.
    """
    call_sid = request.POST.get('CallSid', '')
    caller_phone = request.POST.get('From', '')
    logger.info(f'Incoming call: {call_sid} from {caller_phone}')

    # Determine the WebSocket URL for Twilio Media Streams
    # In production, use wss:// — Twilio requires secure WebSocket
    ws_host = request.get_host()
    # Use the request scheme to determine ws:// or wss://
    ws_scheme = 'wss' if request.is_secure() else 'ws'
    stream_url = f'{ws_scheme}://{ws_host}/ws/call/'

    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="call_sid" value="{call_sid}" />
            <Parameter name="caller_phone" value="{caller_phone}" />
        </Stream>
    </Connect>
    <Say>Sorry, we're having trouble connecting. Please try again later.</Say>
</Response>'''

    return HttpResponse(twiml, content_type='text/xml')


@csrf_exempt
@require_POST
def twilio_sms_status(request):
    """
    Callback for Twilio SMS delivery status updates.
    """
    message_sid = request.POST.get('MessageSid', '')
    status = request.POST.get('MessageStatus', '')
    logger.info(f'SMS {message_sid} status: {status}')
    return HttpResponse('OK')
