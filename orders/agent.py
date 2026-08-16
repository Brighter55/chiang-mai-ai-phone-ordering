"""
Deepgram Voice Agent configuration + order persistence.

The Deepgram Voice Agent API replaces the old DIY pipeline (Deepgram STT +
OpenAI + Deepgram Aura TTS) with a single managed WebSocket. This module
builds the agent's Settings payload (system prompt, models, keyterms,
functions, greeting) and saves orders that arrive via the `place_order`
function call.
"""

import logging
import re
from pathlib import Path

from django.conf import settings

from deepgram.agent.v1 import (
    AgentV1Settings,
    AgentV1SettingsAgent,
    AgentV1SettingsAgentListen,
    AgentV1SettingsAgentListenProvider_V1,
    AgentV1SettingsAudio,
    AgentV1SettingsAudioInput,
    AgentV1SettingsAudioOutput,
)
from deepgram.types.speak_settings_v1 import SpeakSettingsV1
from deepgram.types.speak_settings_v1provider import SpeakSettingsV1Provider_Deepgram
from deepgram.types.think_settings_v1 import ThinkSettingsV1, ThinkSettingsV1FunctionsItem
from deepgram.types.think_settings_v1provider import ThinkSettingsV1Provider_OpenAi

logger = logging.getLogger(__name__)

# Live-edit override: if this file exists (repo root, gitignored), it is used
# as the system prompt with the menu section replaced by live DB menu text.
# Otherwise the embedded VA_SYSTEM_PROMPT template below is used.
VA_PROMPT_FILE = Path(settings.BASE_DIR) / '_dg_va_prompt.txt'

GREETING = (
    f"Thank you for calling {settings.RESTAURANT_NAME}. All our staff are "
    "currently busy assisting other customers, but I can take your order "
    "right away. What can I get for you today?"
)

# Appended to the system prompt regardless of source (file or embedded) —
# teaches the model the place_order → end_conversation sequence.
FUNCTION_CALL_INSTRUCTIONS = """
## Placing the Order (FUNCTION CALLS)
Orders are saved through function calls. Follow this exactly:
1. Once the order is fully confirmed — every item read back with prices, customer name collected, callback phone number collected, total and 20-25 minute ETA given — call `place_order` FIRST, in your very next response, with the complete order details. Do NOT wait for more input from the customer, even if they just say "thanks".
2. Output NO text before the call — no announcements like "I will place your order", no goodbyes, nothing. The FIRST thing in your response must be the `place_order` function call. The system saves the order and sends it to the restaurant; the customer does not need to know about this.
3. After the call, say your natural goodbye ("Thank you, have a great day!").
4. Then call `end_conversation` with reason `order_placed`.
5. Do not generate any text after calling `end_conversation`.
6. CRITICAL: step 4 is mandatory and must happen in this same response, right after the goodbye. Never end a call without `end_conversation`, and never wait for the customer to speak again — otherwise the caller is left on the line in silence.
"""

# Embedded fallback system prompt — same content as the tested _dg_va_prompt.txt
# working copy, but the menu section is a {menu_text} placeholder filled from
# the DB at call time and the restaurant name is injected from settings.
VA_SYSTEM_PROMPT = """You are an AI phone order taker for {restaurant_name}. You take food orders over the phone.

## Your Role
- Be friendly, warm, and efficient — like a great server
- Take orders conversationally, one step at a time
- After each item, briefly confirm just that item (e.g. "Got it, one Pad Thai with shrimp") — do NOT re-read the whole order
- Read back the full order only when the customer asks for a recap or says they're done ordering
- Speak naturally — NEVER use markdown, bold, asterisks, bullet points, or any special characters in your responses

## Matching Customer Speech to Menu Items — CRITICAL
Customers may pronounce dish names in many ways: with a Thai accent, with an English accent, or using descriptive phrases instead of the menu name. You MUST match what they say to the correct menu item using:
- **Sound/phonetic matching**: "cow soy" or "kao soi" → Khao Soi. "pat tie" or "put tie" → Pad Thai. "sigh ooh ah" → Sai Oua. "gang hung lay" → Gaeng Hung Lay.
- **Thai name matching**: if a customer says the Thai name (e.g. "kao pad" = ข้าวผัด = Fried rice, "pad kee mao" = ผัดขี้เมา = Drunken Noodles, "pad krapow" = ผัดกะเพรา = Spicy Basil), match it to the correct menu item. The menu lists Thai script and common Thai pronunciations for each dish — use them.
- **Description matching**: if a customer describes a dish ("the curry noodle soup", "the basil stir fry", "the papaya salad"), match it to the correct item.
- **Partial/fuzzy matching**: if a customer says something close but not exact ("massaman" instead of "Massaman Beef", "drunken noodle" instead of "Drunken Noodles"), use your judgment to find the closest match.
- When in doubt, confirm: "Did you mean [menu item name]?"

## The Menu
{menu_text}

## Understanding Protein Options & Pricing
The menu shows two types of customization:

"Choice of:" — options the customer picks from. Options WITHOUT a price are included in the base price; options that show (+$X) cost that extra amount:
- Some items list proteins (chicken, tofu, vegetables, shrimp) — the customer picks one. If the option has no price it's free; if it shows (+$X), picking that option costs the extra amount.
- Some items list vege types (broccoli vs Asian green veggies) — ask which they prefer.
- Some items are a single "pick one" set where some options cost extra (e.g. Poh Piah: vegetables, cheese, pork (+$3.09), shrimps (+$3.09)) — present ALL the options and note any that have a price.
- If there is NO "Choice of:" line, the dish comes as described — do NOT ask about protein or other choices.

"Spice level:" — shown as a number scale (0 to 5). ONLY ask about spice if the dish's menu entry shows a "Spice level:" line. If it does NOT show one, do NOT ask about spice — the dish comes as-is.

"Add-ons (extra charge):" — these cost extra and are for customers who want ADDITIONAL protein, vegetables, or modifications beyond what's standard. They are optional — only offer them if the customer wants more.

CRITICAL — before asking any customization question, read that specific dish's menu entry and ask ONLY what its entry lists. Never assume a dish has spice or a protein choice just because a similar dish does.

Examples of correct pricing:
- Pad Thai ($17.59) with chicken = $17.59 (chicken is in "Choice of:", no extra charge)
- Pad Thai ($17.59) with extra chicken = $20.68 (base $17.59 + add chicken $3.09)
- Pad Thai ($17.59) with tofu = $17.59 (tofu is in "Choice of:", no extra charge)
- Poh Piah ($6.19) with pork filling = $9.28 (pork (+$3.09) is a paid option in "Choice of:")
- Khao Soi ($17.59) = $17.59 (Khao Soi always comes with chicken drumsticks — no protein choice in "Choice of:")
- Khao Soi ($17.59) with extra chicken = $20.68 (customer wants extra as a paid add-on)
- Do NOT tell customers that choosing chicken adds $3 — it only adds $3 if they ask for EXTRA chicken

## Order Flow
1. The opening greeting is played automatically by the system before your first turn — go straight to taking the order. If the customer asks "who is this?" or "what can you do?", briefly explain you can take their food order for {restaurant_name}.
2. Take their order item by item. For EACH item, read its menu entry and ask ONLY what the entry shows:
   - Ask about spice ONLY if the entry has a "Spice level:" line: "how spicy would you like it, on a scale from 0 to 5?" (0 = no spice, 5 = spiciest). Use the NUMBER, don't list the words.
   - Ask about a choice ONLY if the entry has a "Choice of:" line. Present ALL the options in that line, and note any that have a price (e.g. Poh Piah: "Which filling? Vegetables, cheese, pork (+$3.09), or shrimps (+$3.09)?").
     - If the line lists proteins, ask which they'd like.
     - If it lists veggie types (broccoli vs Asian green veggies), ask which they prefer.
     - If it lists both proteins and veggie types (e.g. Pad See Ew), ask the protein first, then the veggie.
   - If there is NO "Spice level:" or "Choice of:" line, do NOT ask about spice or choices — the dish comes as described. You may still mention paid add-ons if the customer seems interested.
   - For items with BOTH spice level and a choice, ask about the spice level first, then the choice.
3. After each item, briefly confirm just that item — do NOT re-read the entire order
4. Read back the full order with prices only when the customer asks for a recap OR signals they're done (e.g. "that's it", "that's all", "that will be all")
5. Ask for their name — just their name, nothing else
6. After they give you their name, then ask for a callback phone number
7. Give them a total and estimated time
8. Once the order is complete, your very next response must START with the `place_order` function call — no text before it (see "Ending the call" below). Do NOT wait for more input, even if the customer just says "thanks". Then say a natural goodbye, then call `end_conversation`.

## Rules
- ONLY sell items on the menu — if someone asks for something not listed, politely say you don't have it and suggest the closest alternative
- If you're unsure about something, ask the customer to repeat or clarify
- Keep responses concise — under 2 sentences when possible
- Do NOT make up prices or items
- DO NOT use any markdown, asterisks, bold, or formatting symbols in your responses — speak in plain, natural language only
- If the customer wants to cancel or start over, do it cheerfully
- Tell them the order will be ready in about 20 to 25 minutes

## Ending the call
When the order is fully complete — every item confirmed and read back with prices, customer name collected, callback phone number collected, total and 20-25 minute ETA given — close the order in ONE final response:
1. FIRST: call `place_order` with the complete order details. Output NO text before this call — no announcements, no goodbyes, nothing. The response must begin with the function call itself. The system saves the order and sends it to the restaurant.
2. After the call, say a natural goodbye ("Thank you, have a great day!").
3. Then call `end_conversation` to end the call.
CRITICAL: Step 3 is mandatory — you MUST call `end_conversation` (reason: `order_placed`) in this same final response, immediately after the goodbye. Never end a call without it, and never wait for the customer to speak again — otherwise the caller is left on the line in silence.
Do NOT call `end_conversation` until `place_order` has been called — unless there is no order to save (customer changed their mind, wrong number, cannot be heard, etc.).
Never output raw JSON, markdown, or any machine-readable text in your replies — the customer can hear everything you say.
## Current Conversation
Keep track of what's been ordered so far. The customer may add items, remove items, or modify items at any point. If the customer adds or changes an item after a recap, just confirm the change — do not re-read the whole order unless they ask.
"""


def get_menu_text():
    """Build menu text from database menu items."""
    from .models import MenuItem

    items = MenuItem.objects.filter(available=True).order_by('category', 'name')
    if not items.exists():
        return "No menu items configured yet."

    categories = {}
    for item in items:
        cat = item.category or 'Other'
        if cat not in categories:
            categories[cat] = []
        # Include Thai name in the menu listing for cross-lingual matching
        if item.thai_name:
            lines = [f'  - {item.name} — {item.thai_name} — ${item.price:.2f}']
        else:
            lines = [f'  - {item.name} — ${item.price:.2f}']

        if item.modifiers:
            # Separate spice levels, add-ons ("add X"), and choices.
            # Choices may be free ("chicken") or priced alternatives that keep
            # their price ("pork (+$3.09)") — both render in "Choice of:".
            spice_levels = []
            choices = []
            addons = []
            for m in item.modifiers:
                if re.match(r'^\d\s*-\s', m):
                    spice_levels.append(m)
                elif re.match(r'^add\s', m, re.IGNORECASE):
                    addons.append(m)
                else:
                    choices.append(m)

            if spice_levels:
                lines.append('    Spice level: 0 (none) to 5 (extra hot) — pick a number')
            if choices:
                lines.append(f'    Choice of: {", ".join(choices)}')
            if addons:
                lines.append(f'    Add-ons (extra charge): {", ".join(addons)}')

        if item.aliases:
            lines.append(f'    Pronunciations: {", ".join(item.aliases)}')

        categories[cat].append('\n'.join(lines))

    sections = []
    for cat, item_list in categories.items():
        sections.append(f'{cat}\n' + '\n'.join(item_list))

    return '\n\n'.join(sections)


# Deepgram hard-caps keyterm biasing at 500 tokens across ALL keyterms
# (verified empirically on this list: ~2 tokens per word, so ~240 words apply
# but ~246 fail with FAILED_TO_START_LISTENING). Keep the total word count
# under this budget with margin so a future "add more keyterms" can't silently
# break every call. Primary control is a curated _dg_keyterms.txt; this cap is
# a backstop that drops the longest (least distinctive) terms first.
MAX_KEYTERM_WORDS = 220


def load_keyterms():
    """Read curated menu keyterms for STT biasing from _dg_keyterms.txt.

    One keyterm per line (empty lines and #-prefixed lines skipped), deduped
    and lowercased. Passed to the listen provider's `keyterms` field so
    mispronounced Thai dish names ("cow soy" → Khao Soi) get biased toward
    menu vocabulary. Returns [] if the file is missing.
    """
    path = Path(settings.BASE_DIR) / '_dg_keyterms.txt'
    if not path.exists():
        logger.warning('_dg_keyterms.txt not found — running without keyterm biasing')
        return []
    seen = set()
    keyterms = []
    for line in path.read_text(encoding='utf-8').splitlines():
        term = line.strip().lower()
        if term and not term.startswith('#') and term not in seen:
            seen.add(term)
            keyterms.append(term)

    total_words = sum(len(term.split()) for term in keyterms)
    if total_words > MAX_KEYTERM_WORDS:
        dropped = []
        while sum(len(t.split()) for t in keyterms) > MAX_KEYTERM_WORDS:
            longest = max(keyterms, key=lambda t: len(t.split()))
            keyterms.remove(longest)
            dropped.append(longest)
        logger.warning(
            'Keyterm budget exceeded (%d words > %d) — dropped %d keyterms '
            '(longest first) to fit Deepgram\'s 500-token limit: %s',
            total_words, MAX_KEYTERM_WORDS, len(dropped),
            ', '.join(dropped[:10]) + ('…' if len(dropped) > 10 else ''),
        )

    logger.info(f'Loaded {len(keyterms)} STT keyterms from {path.name}')
    return keyterms


def build_system_prompt():
    """Build the system prompt: tested _dg_va_prompt.txt (with live menu) if
    present, else the embedded template. FUNCTION_CALL_INSTRUCTIONS is
    appended to either source."""
    menu_text = get_menu_text()
    restaurant_name = getattr(settings, 'RESTAURANT_NAME', 'Our Restaurant')

    if VA_PROMPT_FILE.exists():
        prompt = VA_PROMPT_FILE.read_text(encoding='utf-8')
        # Replace the menu snapshot in the file with the live menu from the DB.
        # The snapshot sits between "## The Menu" and "## Understanding ...".
        replaced = re.sub(
            r'(## The Menu\n).*?(\n## Understanding Protein Options & Pricing)',
            lambda m: m.group(1) + menu_text + m.group(2),
            prompt,
            flags=re.DOTALL,
        )
        if replaced != prompt:
            prompt = replaced
        else:
            # Markers not found (file edited) — use the file verbatim; it still
            # contains a valid menu snapshot.
            logger.warning('Menu markers not found in %s — using file verbatim', VA_PROMPT_FILE.name)
    else:
        prompt = VA_SYSTEM_PROMPT.format(
            restaurant_name=restaurant_name, menu_text=menu_text
        )

    return prompt.strip() + '\n' + FUNCTION_CALL_INSTRUCTIONS.strip() + '\n'


def build_functions():
    """Function definitions sent to the Voice Agent in think settings.

    `place_order` — client-side: the consumer receives a FunctionCallRequest,
    saves the order + sends SMS, and returns the result.
    `end_conversation` — Deepgram's built-in hangup signal; the consumer
    schedules the Twilio REST hangup when it fires.
    """
    place_order = ThinkSettingsV1FunctionsItem(
        name='place_order',
        description=(
            "Save and send the customer's confirmed order to the restaurant. "
            "Call FIRST, before any text, in the response immediately after "
            "the order is complete: (1) every item confirmed with quantity, "
            "spice level, protein choice, and paid add-ons; (2) the full order "
            "read back with prices; (3) the customer's name; (4) a callback "
            "phone number; (5) the total and the 20-25 minute ETA given. "
            "Output no text before this call. After place_order, speak a "
            "short goodbye, then call end_conversation."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'customer_name': {
                    'type': 'string',
                    'description': "Customer's name as they gave it (first name is sufficient).",
                },
                'customer_phone': {
                    'type': 'string',
                    'description': "Customer's callback phone number as spoken, e.g. '314-555-0123'.",
                },
                'items': {
                    'type': 'array',
                    'description': 'Every item in the confirmed order using exact menu names.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'name': {
                                'type': 'string',
                                'description': 'Exact menu item name as listed on the menu.',
                            },
                            'quantity': {
                                'type': 'integer',
                                'description': 'Number of this item.',
                                'minimum': 1,
                            },
                            'price': {
                                'type': 'number',
                                'description': 'Unit price in USD including paid add-ons (free choices do not change price).',
                            },
                            'notes': {
                                'type': 'string',
                                'description': "Customizations, e.g. 'spice level 5, with chicken, extra sauce'.",
                            },
                        },
                        'required': ['name', 'quantity', 'price'],
                    },
                },
                'total': {
                    'type': 'number',
                    'description': 'Grand total in USD for the entire order.',
                },
                'notes': {
                    'type': 'string',
                    'description': 'Order-level notes or special requests, or empty string.',
                },
            },
            'required': ['customer_name', 'customer_phone', 'items', 'total'],
        },
    )

    end_conversation = ThinkSettingsV1FunctionsItem(
        name='end_conversation',
        description=(
            "End the phone call. Call after saying a natural goodbye — either "
            "after place_order has saved the order, or when the call should end "
            "without an order (customer changed their mind, wrong number, "
            "cannot be heard, etc.). Do not generate text after calling it."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'reason': {
                    'type': 'string',
                    'description': 'Why the call is ending.',
                    'enum': ['order_placed', 'no_order_needed', 'customer_goodbye', 'unable_to_help'],
                }
            },
            'required': ['reason'],
        },
    )

    return [place_order, end_conversation]


def build_agent_settings():
    """Build the Voice Agent Settings payload sent once per call.

    Audio is Twilio-compatible mulaw 8kHz on both sides. STT uses nova-3
    (the only model supporting keyterm biasing for Thai dish names), the LLM
    is gpt-4o-mini at temperature 0 (deterministic order-taking), and TTS is
    Deepgram Aura. The greeting is spoken by the agent automatically.
    """
    return AgentV1Settings(
        type='Settings',
        audio=AgentV1SettingsAudio(
            input=AgentV1SettingsAudioInput(encoding='mulaw', sample_rate=8000),
            output=AgentV1SettingsAudioOutput(
                encoding='mulaw', sample_rate=8000, container='none',
            ),
        ),
        agent=AgentV1SettingsAgent(
            listen=AgentV1SettingsAgentListen(
                # v1 provider for Nova models (v2 is Flux-only — Deepgram
                # rejects nova models on v2 with "Invalid tier 'nova'").
                provider=AgentV1SettingsAgentListenProvider_V1(
                    version='v1',
                    type='deepgram',
                    model=settings.DEEPGRAM_VOICE_AGENT_STT_MODEL,
                    keyterms=load_keyterms(),
                ),
            ),
            think=ThinkSettingsV1(
                provider=ThinkSettingsV1Provider_OpenAi(
                    type='open_ai',
                    model=settings.DEEPGRAM_VOICE_AGENT_LLM_MODEL,
                    temperature=settings.DEEPGRAM_VOICE_AGENT_TEMPERATURE,
                ),
                prompt=build_system_prompt(),
                functions=build_functions(),
            ),
            speak=SpeakSettingsV1(
                provider=SpeakSettingsV1Provider_Deepgram(
                    type='deepgram',
                    model=settings.DEEPGRAM_VOICE_AGENT_TTS_MODEL,
                ),
            ),
            greeting=GREETING,
        ),
    )


def save_order_from_agent(order_data: dict, call_sid: str = ''):
    """
    Save an extracted order to the database.

    `order_data` is the arguments dict from the `place_order` function call:
        {customer_name, customer_phone, items: [{name, quantity, price, notes}],
         total, notes}
    """
    from .models import Order, OrderItem, MenuItem

    if not order_data:
        return None

    # Create the order
    order = Order.objects.create(
        customer_name=order_data.get('customer_name', 'Unknown'),
        customer_phone=order_data.get('customer_phone', ''),
        status='new',
        total=order_data.get('total', 0),
        notes=order_data.get('notes', ''),
        call_sid=call_sid,
    )

    # Create order items
    for item_data in order_data.get('items', []):
        item_name = item_data.get('name', 'Unknown Item')
        # Try to match to a menu item
        menu_item = MenuItem.objects.filter(
            name__iexact=item_name, available=True
        ).first()

        OrderItem.objects.create(
            order=order,
            menu_item=menu_item,
            name=item_name,
            quantity=item_data.get('quantity', 1),
            price=item_data.get('price', 0),
            notes=item_data.get('notes', ''),
        )

    return order
