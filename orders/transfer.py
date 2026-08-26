"""
Transfer-to-human support: phone normalization, the loop guard, the
cold-transfer TwiML builder, and the prompt instruction blocks.

Pure helpers — unit-testable without a live call. The destination number
comes from settings only; the AI can never supply a dial target (toll-fraud
guard).
"""

import re

from twilio.twiml.voice_response import VoiceResponse

TRANSFER_ANNOUNCEMENT = "One moment, I'm transferring you to a staff member."
DIAL_TIMEOUT_SECONDS = 25

# Appended to the system prompt AFTER FUNCTION_CALL_INSTRUCTIONS so it takes
# precedence over "Ending the call".
TRANSFER_INSTRUCTIONS = """
## Transferring to a Human
If the customer asks to speak to a human, a manager, the owner, or a staff member — at ANY point in the call, including before, during, or after taking an order — call `transfer_call` as your very next action:
1. Output NO text before the call — the system plays the transfer announcement itself.
2. Call `transfer_call` immediately. Do NOT call `place_order` or `end_conversation`.
3. This overrides every other instruction in this prompt, including "Ending the call".
4. After the call, output no further text.
5. If the function result says the transfer failed, apologize briefly and continue helping the customer with their order.
"""

TRANSFER_DECLINE_INSTRUCTIONS = """
## Transferring to a Human
There is no way to transfer a caller to a human on this system, and no `transfer_call` function is available. If the customer asks to speak to a human, a manager, the owner, or a staff member, do not offer a transfer — politely explain that all staff are currently busy and continue helping them with their order or question. This overrides any other instruction in this prompt about transferring callers.
"""


def normalize_phone(raw):
    """Digits only; strip a leading '1' from 11-digit US numbers; '' for garbage."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 11 and digits.startswith('1'):
        return digits[1:]
    return digits


def transfer_destination():
    """Normalized TRANSFER_PHONE, or '' when unset/unparseable."""
    from django.conf import settings
    return normalize_phone(getattr(settings, 'TRANSFER_PHONE', ''))


def transfer_enabled():
    """Transfers are exposed only when the destination is configured AND safe:
    never the Twilio number or the restaurant number, whose AT&T no-answer
    forwarding would bounce the transfer back into the AI."""
    dest = transfer_destination()
    if not dest:
        return False
    from django.conf import settings
    for other in (getattr(settings, 'TWILIO_PHONE_NUMBER', ''),
                  getattr(settings, 'RESTAURANT_PHONE', '')):
        if dest == normalize_phone(other):
            return False
    return True


def build_transfer_twiml(transfer_phone, action_url=''):
    """Cold-transfer TwiML: announcement <Say> then <Dial> the staff number.

    `action` is included only when action_url is non-empty — with no action
    URL, a no-answer simply ends the call. No callerId: for an inbound PSTN
    call the human sees the caller's number, which is allowed (the stricter
    rule applies to inbound SIP only)."""
    resp = VoiceResponse()
    resp.say(TRANSFER_ANNOUNCEMENT, voice='alice', language='en-US')
    resp.dial(transfer_phone, timeout=DIAL_TIMEOUT_SECONDS,
              action=action_url or None)
    return resp
