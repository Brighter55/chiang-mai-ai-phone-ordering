"""
Send order notifications to the restaurant phone via Twilio SMS.
"""

import logging
from django.conf import settings
from twilio.rest import Client

logger = logging.getLogger(__name__)


def get_twilio_client():
    """Get authenticated Twilio client."""
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_order_sms(order):
    """
    Format and send an order as SMS to the restaurant phone.

    Example message:
        New Order #42 | John
        Pickup
        2x Pad Thai — $24.00
        1x Spring Rolls — $6.00
        Total: $30.00
        Phone: 314-555-0123
    """

    items_text = '\n'.join(
        f'{item.quantity}x {item.name} — ${item.line_total:.2f}'
        + (f'\n   ({item.notes})' if item.notes else '')
        for item in order.items.all()
    )

    message = (
        f'🛎️ New Order #{order.id} | {order.customer_name}\n'
        f'Pickup\n'
        f'{items_text}\n'
        f'──────────\n'
        f'Total: ${order.total:.2f}\n'
        f'📞 {order.customer_phone}'
    )

    if order.notes:
        message += f'\n📝 {order.notes}'

    logger.info(f'📨 SMS content for Order #{order.id}:\n{message}')

    client = get_twilio_client()

    try:
        sms = client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=settings.RESTAURANT_PHONE,
        )
        order.sms_sent = True
        order.save(update_fields=['sms_sent'])
        logger.info(f'SMS sent for Order #{order.id}: {sms.sid}')
        return sms.sid
    except Exception as e:
        logger.warning(f'SMS send failed (A2P?): {e} — content was logged above')
        # Don't mark as sent so it retries later when messaging is active
        return None
