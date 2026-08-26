"""
Management command to push an existing local Order to Clover.

Use for manual retry after a failed push, or to verify the integration
against the sandbox without placing a phone call.

Usage:
    python manage.py push_order_to_clover 42
    python manage.py push_order_to_clover 42 --force
"""

from django.core.management.base import BaseCommand, CommandError

from orders.clover import get_clover_client, send_order_to_clover
from orders.models import Order


class Command(BaseCommand):
    help = 'Push an existing local order to Clover as an open ticket.'

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=int, help='Local Order id to push.')
        parser.add_argument(
            '--force', action='store_true',
            help='Re-push even if the order was already pushed to Clover.',
        )

    def handle(self, *args, **options):
        order_id = options['order_id']
        force = options['force']

        if get_clover_client() is None:
            raise CommandError(
                'Clover not configured. Set CLOVER_API_TOKEN and CLOVER_MERCHANT_ID '
                '(and optionally CLOVER_BASE_URL) in the environment.'
            )

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            raise CommandError(f'Order #{order_id} not found')

        if order.clover_pushed and not force:
            self.stdout.write(self.style.WARNING(
                f'Order #{order_id} was already pushed to Clover '
                f'(clover_order_id={order.clover_order_id!r}). Use --force to re-push.'
            ))
            return

        clover_order_id = send_order_to_clover(order)
        order.refresh_from_db()

        if clover_order_id:
            self.stdout.write(self.style.SUCCESS(
                f'Order #{order_id} pushed to Clover: order id {clover_order_id}'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'Push failed for Order #{order_id}: {order.clover_error or "see logs"}'
            ))
            raise CommandError('Clover push failed')
