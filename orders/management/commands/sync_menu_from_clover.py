"""
Management command to sync the menu from the Clover catalog into MenuItem.

Clover is the source of truth for names/prices/modifiers. Curated phonetic
`aliases`/`thai_name` on existing items are PRESERVED (matched by name) so
STT keyterms and Thai-name matching stay intact.

Usage:
    python manage.py sync_menu_from_clover --dry-run
    python manage.py sync_menu_from_clover
    python manage.py sync_menu_from_clover --seed-aliases
    python manage.py sync_menu_from_clover --delete-missing
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orders.clover import (
    CloverError,
    build_clover_modifiers,
    get_clover_client,
)
from orders.models import MenuItem

# Category used for Clover items that have no category assigned.
DEFAULT_CATEGORY = 'Uncategorized'


def _cents_to_dollars(cents):
    return cents / 100 if cents is not None else 0


class Command(BaseCommand):
    help = 'Sync the menu from the Clover catalog into the local MenuItem table.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would change without touching the database.',
        )
        parser.add_argument(
            '--seed-aliases', action='store_true',
            help='For NEW items, copy aliases/thai_name from seed_menu.SAMPLE_MENU by name.',
        )
        parser.add_argument(
            '--delete-missing', action='store_true',
            help='Hard-delete local items that have a clover_item_id but are gone from Clover '
                 '(default: mark them unavailable to preserve aliases/history).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        seed_aliases = options['seed_aliases']
        delete_missing = options['delete_missing']

        client = get_clover_client()
        if client is None:
            raise CommandError(
                'Clover not configured. Set CLOVER_API_TOKEN and CLOVER_MERCHANT_ID '
                '(and optionally CLOVER_BASE_URL) in the environment.'
            )

        self.stdout.write(f'Fetching catalog from {client.base_url} …')
        try:
            categories = client.fetch_categories()
            items = client.fetch_items()
            modifiers = client.fetch_modifiers()
        except CloverError as e:
            raise CommandError(str(e)) from e

        cat_by_id = {c.get('id'): c.get('name') for c in categories}
        modifier_by_id = {m.get('id'): m for m in modifiers}

        # The /items list endpoint omits modifierGroups entirely, no matter the
        # expand — only the per-item detail returns them. Fetch each item's
        # detail to get the groups attached to it (1 request per item; fine for
        # an on-demand sync).
        self.stdout.write('Fetching per-item modifier groups …')
        item_groups = {}
        for item in items:
            iid = item.get('id')
            if not iid:
                continue
            try:
                detail = client._request(
                    'GET', f'/items/{iid}',
                    params={'expand': 'modifierGroups,modifierGroups.modifiers'},
                )
            except CloverError:
                continue
            raw = detail.get('modifierGroups') or {}
            groups = raw.get('elements') if isinstance(raw, dict) else (raw or [])
            item_groups[iid] = groups

        self.stdout.write(
            f'Fetched {len(items)} items, {len(categories)} categories, '
            f'{sum(1 for g in item_groups.values() if g)} items with modifier groups'
        )

        sample_by_name = {}
        if seed_aliases:
            try:
                from orders.management.commands.seed_menu import SAMPLE_MENU
                sample_by_name = {s['name'].lower(): s for s in SAMPLE_MENU}
            except ImportError:
                self.stderr.write('seed_menu import failed — --seed-aliases disabled')

        existing = {m.name.lower(): m for m in MenuItem.objects.all()}
        clover_names = set()

        created = updated = unchanged = 0

        for item in items:
            name = (item.get('name') or '').strip()
            if not name:
                continue
            clover_names.add(name.lower())

            price = _cents_to_dollars(item.get('price'))
            category = DEFAULT_CATEGORY
            for cat in (item.get('categories') or []):
                cat_name = cat_by_id.get(cat.get('id')) if isinstance(cat, dict) else None
                if cat_name:
                    category = cat_name
                    break
            available = not bool(item.get('hidden', False))

            rich_groups, flat_modifiers = build_clover_modifiers(
                item_groups.get(item.get('id'), []), modifier_by_id
            )

            data = {
                'price': price,
                'category': category,
                'description': item.get('description') or '',
                'available': available,
                'clover_item_id': item.get('id'),
                'clover_modifiers': rich_groups,
                'modifiers': flat_modifiers,
            }

            existing_item = existing.get(name.lower())
            if existing_item is None:
                if dry_run:
                    created += 1
                    continue
                sample = sample_by_name.get(name.lower(), {})
                with transaction.atomic():
                    MenuItem.objects.create(
                        name=name,
                        aliases=sample.get('aliases', []),
                        thai_name=sample.get('thai_name', ''),
                        **data,
                    )
                created += 1
                self.stdout.write(f'  + {name} (${price:.2f})')
            else:
                # Preserve curated phonetic data.
                data.pop('aliases', None)
                data.pop('thai_name', None)
                changed = False
                for key, value in data.items():
                    if getattr(existing_item, key) != value:
                        if not dry_run:
                            setattr(existing_item, key, value)
                        changed = True
                if changed:
                    if not dry_run:
                        existing_item.save()
                    updated += 1
                    if existing_item.clover_item_id != data['clover_item_id']:
                        self.stdout.write(f'  ~ {name} linked to Clover item {data["clover_item_id"]}')
                else:
                    unchanged += 1

        # Stale local items that were Clover-linked but no longer exist in Clover.
        stale = [
            m for m in existing.values()
            if m.clover_item_id and m.name.lower() not in clover_names
        ]
        if stale:
            self.stdout.write(self.style.WARNING(
                f'{len(stale)} local item(s) gone from Clover: '
                + ', '.join(m.name for m in stale)
            ))
            if not dry_run:
                if delete_missing:
                    for m in stale:
                        m.delete()
                else:
                    for m in stale:
                        m.available = False
                        m.save(update_fields=['available'])

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN — would create {created}, update {updated}, '
                f'leave {unchanged} unchanged, '
                f'{len(stale)} stale ({("delete" if delete_missing else "unavailable")})'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Synced: {created} new, {updated} updated, {unchanged} unchanged '
                f'(total: {MenuItem.objects.count()})'
            ))
