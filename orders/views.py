"""
Twilio webhook views — handle incoming calls and SMS status callbacks.
"""

import logging

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from twilio.twiml.voice_response import VoiceResponse

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def twilio_voice_webhook(request):
    """
    Called by Twilio when a customer calls your Twilio number.
    Returns TwiML that connects the call to our WebSocket audio stream.

    The restaurant phone has already rung via AT&T call forwarding
    (no-answer / busy) before this endpoint is hit. The AI just answers.
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

    # Absolute <Dial action> URL for transfer results — Twilio executes this
    # itself, so force https even when the webhook arrived over http.
    transfer_result_url = request.build_absolute_uri(
        reverse('twilio-transfer-result')).replace('http://', 'https://', 1)

    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="call_sid" value="{call_sid}" />
            <Parameter name="caller_phone" value="{caller_phone}" />
            <Parameter name="transfer_result_url" value="{transfer_result_url}" />
        </Stream>
    </Connect>
    <Say>Sorry, we're having trouble connecting. Please try again later.</Say>
</Response>'''

    return HttpResponse(twiml, content_type='text/xml')


@csrf_exempt
@require_POST
def twilio_transfer_result(request):
    """<Dial action> callback. Fires when the transfer leg ends while the
    caller is still on the line. DialCallStatus: completed (the human answered
    and the leg ended — an empty <Response/> is what ends the caller's leg),
    or no-answer/busy/failed (the caller is still on the line — apologize and
    hang up)."""
    call_sid = request.POST.get('CallSid', '')
    status = request.POST.get('DialCallStatus', '')
    dial_call_sid = request.POST.get('DialCallSid', '')
    logger.info(f'📞 Transfer result — call {call_sid}, DialCallStatus={status}, '
                f'DialCallSid={dial_call_sid}')

    if status in ('completed', 'answered', 'canceled'):
        # The call is already over (or the caller hung up) — empty TwiML.
        return HttpResponse('<Response/>', content_type='text/xml')

    resp = VoiceResponse()
    resp.say("I'm sorry, we couldn't reach a staff member right now. "
             "Please call back during business hours, or stop by the restaurant. "
             "Goodbye.")
    resp.hangup()
    return HttpResponse(str(resp), content_type='text/xml')


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
