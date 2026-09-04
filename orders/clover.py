"""
Clover POS integration — menu sync + order placement.

Mirrors the notify.py style: a thin client factory built from settings, and
module-level helpers that swallow errors and return None so a Clover outage
can never break a phone call (the local order + SMS backup still happen).
"""

import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10


class CloverError(Exception):
    """Raised on Clover API failures (HTTP errors, config errors)."""


class CloverConfigError(CloverError):
    """Raised when required Clover settings are missing."""


def get_clover_client():
    """Build an authenticated CloverClient from settings, or None if not configured."""
    token = settings.CLOVER_API_TOKEN
    merchant_id = settings.CLOVER_MERCHANT_ID
    if not token or not merchant_id:
        logger.warning(
            'Clover not configured (CLOVER_API_TOKEN / CLOVER_MERCHANT_ID missing) — skipping Clover'
        )
        return None
    return CloverClient(
        merchant_id=merchant_id,
        token=token,
        base_url=settings.CLOVER_BASE_URL,
        order_type_name=settings.CLOVER_ORDER_TYPE_NAME,
    )


class CloverClient:
    """Minimal Clover REST API v3 client (Bearer token auth)."""

    def __init__(self, merchant_id, token, base_url, order_type_name):
        self.merchant_id = merchant_id
        self.token = token
        self.base_url = base_url.rstrip('/')
        self.order_type_name = order_type_name
        self._order_type_id = None
        self._order_type_looked_up = False

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _url(self, path):
        return f'{self.base_url}/v3/merchants/{self.merchant_id}{path}'

    def _request(self, method, path, params=None, json_body=None):
        try:
            resp = requests.request(
                method,
                self._url(path),
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            status = getattr(e.response, 'status_code', 'N/A')
            body = ''
            if e.response is not None:
                body = e.response.text[:500]
            logger.warning('Clover %s %s failed (%s): %s — %s', method, path, status, e, body)
            raise CloverError(f'Clover {method} {path} failed: {e}') from e

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------
    # Read: catalog
    # ------------------------------------------------------------------

    def fetch_categories(self):
        data = self._request('GET', '/categories')
        return data.get('elements', [])

    def fetch_items(self, limit=250, expand='categories'):
        """Fetch all inventory items, paginating until exhausted."""
        items = []
        offset = 0
        while True:
            params = {'limit': limit, 'offset': offset}
            if expand:
                params['expand'] = expand
            data = self._request('GET', '/items', params=params)
            batch = data.get('elements', [])
            items.extend(batch)
            if len(batch) < limit:
                break
            offset += len(batch)
        return items

    def fetch_modifier_groups(self):
        data = self._request('GET', '/modifier_groups', params={'expand': 'modifiers'})
        return data.get('elements', [])

    def fetch_modifiers(self):
        data = self._request('GET', '/modifiers')
        return data.get('elements', [])

    def fetch_order_types(self):
        data = self._request('GET', '/order_types')
        return data.get('elements', [])

    # ------------------------------------------------------------------
    # Order type
    # ------------------------------------------------------------------

    def lookup_order_type(self):
        """Return the Clover order-type id for CLOVER_ORDER_TYPE_NAME (memoized).

        If CLOVER_ORDER_TYPE_ID is set, use it directly — many API tokens can't
        read /order_types (401), so this bypasses the lookup entirely. Otherwise
        best-effort name lookup; failures return None so the order still gets
        pushed — just without an order type. Clover accepts atomic orders with
        no orderType.
        """
        if self._order_type_looked_up:
            return self._order_type_id
        self._order_type_looked_up = True

        override = (settings.CLOVER_ORDER_TYPE_ID or '').strip()
        if override:
            self._order_type_id = override
            logger.info('Clover order type from CLOVER_ORDER_TYPE_ID: %s', override)
            return override

        name = (self.order_type_name or '').strip().lower()
        try:
            order_types = self.fetch_order_types()
        except CloverError:
            logger.warning(
                'Clover order-type lookup failed (token needs Orders scope to read '
                'order types) — order will be pushed without an order type'
            )
            return None

        for ot in order_types:
            candidate = str(ot.get('name') or ot.get('label') or '').strip().lower()
            if candidate == name:
                self._order_type_id = ot.get('id')
                logger.info('Clover order type "%s" → id %s', ot.get('name'), self._order_type_id)
                return self._order_type_id

        logger.warning(
            'Clover order type "%s" not found in %s — order will be pushed without an order type',
            self.order_type_name,
            [ot.get('name') for ot in order_types],
        )
        return None

    # ------------------------------------------------------------------
    # Write: orders
    # ------------------------------------------------------------------

    def create_atomic_order(self, order_cart):
        """POST an atomic order; returns the response JSON."""
        return self._request('POST', '/atomic_order/orders', json_body={'orderCart': order_cart})


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def dollars_to_cents(value):
    """Decimal/float/str dollars → integer cents."""
    from decimal import Decimal, ROUND_HALF_UP

    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _norm(s):
    """Normalize a string for comparison: lowercase, strip punctuation/spaces."""
    if not s:
        return ''
    return re.sub(r'[^a-z0-9]+', '', str(s).lower())


def _group_kind(group):
    """Classify a Clover modifier group: spice / choice / addon."""
    name = _norm(group.get('name') or '')
    modifiers = group.get('modifiers') or []
    min_required = group.get('minRequired', 0)
    max_allowed = group.get('maxAllowed')

    if 'spice' in name or 'heat' in name:
        return 'spice'
    names = [str(m.get('name') or '').strip() for m in modifiers if m.get('name')]
    if names and all(re.match(r'^\d', n) for n in names):
        return 'spice'
    if min_required == 0:
        # Optional single-select groups with several alternatives are really a
        # choice (e.g. Iced? -> iced / no iced) — the "no pick" is implicit.
        # A lone optional extra (e.g. Side Order -> fried egg) stays an add-on.
        if max_allowed == 1 and len(modifiers) > 1:
            return 'choice'
        return 'addon'
    return 'choice'


def _flat_modifier_entry(kind, name, price_cents):
    """Render one Clover modifier into the flat prompt-format string."""
    price = f'(+${price_cents / 100:.2f})'
    if kind == 'spice':
        # Keep the 'N - label' shape so get_menu_text renders a Spice level line.
        if re.match(r'^\d\s*[-–: ]', name.strip()):
            return name.strip()
        return f'0 - {name.strip()}'
    if kind == 'addon':
        # Lowercase to match the existing menu convention ("add chicken", not "add Chicken").
        addon = name.strip().lower()
        return f'add {addon} {price}' if price_cents else f'add {addon}'
    # choice
    return f'{name.strip()} {price}' if price_cents else name.strip()


def build_clover_modifiers(modifier_groups, modifier_by_id):
    """
    Convert raw Clover modifier groups into the stored MenuItem.clover_modifiers
    structure and derive the flat prompt `modifiers` list.

    Group modifiers may arrive as full dicts (expand) or `{id}` refs — refs are
    resolved via modifier_by_id BEFORE classification so the spice/choice/addon
    heuristic sees real names.

    Returns (rich_groups, flat_modifiers).
    """
    rich = []
    flat = []
    for group in modifier_groups or []:
        mods = []
        group_mods = group.get('modifiers') or []
        if isinstance(group_mods, dict):
            # Expanded groups come back as {"elements": [...]} — unwrap.
            group_mods = group_mods.get('elements') or []
        for m in group_mods:
            if isinstance(m, dict):
                if m.get('name'):
                    mod = m
                elif m.get('id'):
                    mod = modifier_by_id.get(m.get('id')) or {}
                else:
                    mod = {}
            elif isinstance(m, str):
                # Clover sometimes returns bare string modifier ids instead of objects.
                mod = modifier_by_id.get(m) or {}
            else:
                mod = {}
            name = str(mod.get('name') or '').strip()
            if not name:
                continue
            mods.append({
                'id': mod.get('id'),
                'name': name,
                'price': int(mod.get('price') or 0),
                'alternateName': mod.get('alternateName') or '',
            })
        if not mods:
            continue
        kind = _group_kind({**group, 'modifiers': mods})
        for mod in mods:
            flat.append(_flat_modifier_entry(kind, mod['name'], mod['price']))
        rich.append({
            'id': group.get('id'),
            'name': group.get('name') or '',
            'min': group.get('minRequired', 0),
            'max': group.get('maxAllowed', 0),
            'kind': kind,
            'modifiers': mods,
        })
    return rich, flat


def resolve_item_options(menu_item, chosen_options):
    """
    Resolve the LLM-emitted option names to Clover modifier entries.

    Returns (modifications, unresolved):
      modifications — list of {'modifier': {'id'}, 'name', 'amount'} for the
                      atomic-order line item
      unresolved    — option strings that matched nothing (fall back to notes)
    """
    modifications = []
    unresolved = []
    groups = (menu_item.clover_modifiers or []) if menu_item else []

    def _match_in(group):
        for mod in group.get('modifiers', []):
            if _norm(mod.get('name')) == norm or _norm(mod.get('alternateName')) == norm:
                return mod
        return None

    def _containment_in(group):
        for mod in group.get('modifiers', []):
            mod_norm = _norm(mod.get('name'))
            alt_norm = _norm(mod.get('alternateName'))
            if mod_norm and (norm in mod_norm or mod_norm in norm):
                return mod
            if alt_norm and (norm in alt_norm or alt_norm in norm):
                return mod
        return None

    for opt in chosen_options or []:
        opt = str(opt).strip()
        if not opt:
            continue
        norm = _norm(opt)
        target = None

        # Negation phrases ("no X", "without X") say what the customer does NOT
        # want. They must never auto-select a real modifier by containment —
        # "no vegetables" must not select the "vegetables" modifier. They fall
        # through to the line note unless an EXACT modifier matches above (e.g.
        # Thai Iced Tea's literal "no iced" modifier).
        # Detect on the raw option's first word: `_norm` strips spaces, which
        # would turn "no vegetables" into "novegetables" and defeat the check.
        first_word = re.split(r'[^a-z0-9]+', str(opt).lower(), maxsplit=1)[0]
        is_negation = first_word in {'no', 'not', 'without', 'dont', 'don'}

        # 1. Bare integer 0..5 → spice modifier whose name starts with that digit.
        if norm.isdigit() and norm in '012345':
            for group in groups:
                if group.get('kind') == 'spice':
                    for mod in group.get('modifiers', []):
                        if re.match(rf'^{norm}\b', str(mod.get('name') or '').strip()):
                            target = mod
                            break
                    if target:
                        break

        # 2. Options phrased as an add-on ("add X") must resolve in an addon
        #    group FIRST — otherwise "add chicken" could match the free
        #    choice "chicken" by containment.
        if not target and norm.startswith('add'):
            for group in groups:
                if group.get('kind') == 'addon':
                    target = _match_in(group) or _containment_in(group)
                    if target:
                        break

        # 3. Exact match on name or alternateName across all groups.
        if not target:
            for group in groups:
                target = _match_in(group)
                if target:
                    break

        # 4. Token containment (one normalized string inside the other).
        #    Skipped for negation phrases — see `is_negation` above.
        if not target and not is_negation:
            for group in groups:
                target = _containment_in(group)
                if target:
                    break

        if target:
            modifications.append({
                'modifier': {'id': target['id']},
                'name': target['name'],
                'amount': int(target.get('price') or 0),
            })
        else:
            unresolved.append(opt)

    # Dedupe: if a single-choice group (max == 1) got multiple picks, keep the
    # first and move the rest to unresolved.
    by_group = {}
    for group in groups:
        for mod in group.get('modifiers', []):
            by_group[mod.get('id')] = group
    kept = []
    seen_groups = {}
    for mod in modifications:
        group = by_group.get(mod['modifier']['id'])
        gid = group.get('id') if group else None
        if gid and group.get('max') == 1 and gid in seen_groups:
            unresolved.append(mod['name'])
            continue
        seen_groups[gid] = True
        kept.append(mod)
    return kept, unresolved


def build_atomic_order_payload(order, order_type_id=None):
    """
    Build the orderCart payload for POST /atomic_order/orders from a local Order.

    Raises CloverError if a line item can't be linked to a Clover item.
    Special instructions — each item's `notes` plus any modifier string that
    matched no real Clover modifier — are attached to that line item as its
    `note` field (Clover's atomic-order lineItems accept a free-form note).
    Returns (payload, unresolved_notes) where unresolved_notes holds the
    per-item note text for logging.
    """
    from .models import OrderItem

    line_items = []
    unresolved_by_line = []
    for oi in order.items.all():
        menu_item = oi.menu_item
        if menu_item is None or not menu_item.clover_item_id:
            raise CloverError(
                f'Order item "{oi.name}" has no linked Clover item '
                f'(menu_item={"None" if menu_item is None else menu_item.name}, '
                f'clover_item_id={getattr(menu_item, "clover_item_id", "")!r})'
            )

        modifications, unresolved = resolve_item_options(menu_item, oi.modifiers or [])
        paid_cents = sum(int(m.get('amount') or 0) for m in modifications)
        line_price_cents = max(dollars_to_cents(oi.price) - paid_cents, 0)

        # Special instructions reach the ticket as the line-item `note` (Clover's
        # atomic-order lineItems accept a free-form `note`). Two sources feed it:
        # the LLM's item `notes` field (the contract for requests that aren't a
        # listed option, e.g. "no vegetables") and any modifier strings that
        # matched no real Clover modifier (defensive — the model sometimes emits
        # such requests in `modifiers`). Dedupe, preserve order.
        note_parts = []
        for part in list(unresolved or []) + ([oi.notes] if oi.notes and oi.notes.strip() else []):
            part = str(part).strip()
            if part and part not in note_parts:
                note_parts.append(part)
        note = '; '.join(note_parts)

        # Clover's atomic order ignores `unitQty`/`quantity` for fixed-price
        # items — quantity is represented as one line item per unit. Expand.
        for _ in range(int(oi.quantity)):
            line_item = {
                'item': {'id': menu_item.clover_item_id},
                'name': oi.name,
                'price': line_price_cents,
                'modifications': modifications,
            }
            if note:
                line_item['note'] = note
            line_items.append(line_item)
        if note:
            unresolved_by_line.append(note)

    order_cart = {
        'currency': 'USD',
        'lineItems': line_items,
    }
    if order_type_id:
        order_cart['orderType'] = {'id': order_type_id}

    return order_cart, unresolved_by_line


def extract_order_id(resp):
    """Extract the created order id from an atomic-order response (shape varies)."""
    if not isinstance(resp, dict):
        return None
    for key in ('order', 'id'):
        val = resp.get(key)
        if isinstance(val, dict) and val.get('id'):
            return val['id']
        if isinstance(val, str) and val:
            return val
    return None


def send_order_to_clover(order):
    """
    Push a local Order to Clover as an open "Take out" atomic order.

    Never raises to the caller — on failure records order.clover_error and
    returns None (the local order + SMS are the source of truth / backup).
    Returns the Clover order id on success.
    """
    client = get_clover_client()
    if client is None:
        return None

    try:
        order_type_id = client.lookup_order_type()
        payload, unresolved = build_atomic_order_payload(order, order_type_id=order_type_id)
        resp = client.create_atomic_order(payload)
        clover_order_id = extract_order_id(resp)

        if not clover_order_id:
            raise CloverError(f'Atomic-order response had no id: {str(resp)[:300]}')

        order.clover_order_id = clover_order_id
        order.clover_pushed = True
        order.clover_error = ''
        order.save(update_fields=['clover_order_id', 'clover_pushed', 'clover_error'])
        logger.info(f'Clover order created for Order #{order.id}: {clover_order_id}')
        return clover_order_id
    except CloverError as e:
        order.clover_error = str(e)
        order.save(update_fields=['clover_error'])
        logger.warning(
            f'Clover push failed for Order #{order.id}: {e} — SMS already sent, local order kept'
        )
        return None
