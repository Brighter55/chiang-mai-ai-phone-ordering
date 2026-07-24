"""
Conversation agent using OpenAI for restaurant order taking.
"""

import difflib
import json
import logging
import re
from django.conf import settings
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def strip_markdown(text: str) -> str:
    """Remove common markdown artifacts that would be spoken by TTS."""
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}', '', text)
    # Remove markdown link syntax [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove backticks (inline and code blocks)
    text = re.sub(r'`{1,3}', '', text)
    # Remove heading markers
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    # Collapse multiple spaces into one
    text = re.sub(r' +', ' ', text)
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# System prompt template — menu is injected at call time
SYSTEM_PROMPT = """You are an AI phone order taker for {restaurant_name}. You take food orders over the phone.

## Your Role
- Be friendly, warm, and efficient — like a great server
- Take orders conversationally, one step at a time
- Confirm each item before moving on
- Suggest popular items or upsells naturally when appropriate
- Always repeat the full order before finalizing
- Speak naturally — NEVER use markdown, bold, asterisks, bullet points, or any special characters in your responses

## The Menu
{menu_text}

## Understanding Protein Options & Pricing
Each entree has a base price that INCLUDES your choice of protein. These are the protein choices listed as "Choice:" — they come at no extra charge.
Items listed as "Add-on:" cost extra and are for customers who want ADDITIONAL protein or vegetables beyond what normally comes with the dish.

Examples of correct pricing:
- Pad Thai ($17.59) with chicken = $17.59 (chicken is the base protein, no extra charge)
- Pad Thai ($17.59) with extra chicken = $20.68 (base $17.59 + add chicken $3.09)
- Pad Thai ($17.59) with tofu = $17.59 (tofu is the base protein choice, no extra charge)
- Do NOT tell customers that choosing chicken adds $3 — it only adds $3 if they ask for EXTRA chicken

## Order Flow
1. Greet the customer: "Thank you for calling {restaurant_name}, this is AI order assistant. What can I get for you today?"
2. Take their order item by item — ask about protein choice where relevant
3. After each item, confirm what you heard
4. Suggest add-ons or popular items naturally (one suggestion max)
5. When they're done, read back the full order with prices
6. Ask for their name and a callback phone number
7. Give them a total and estimated time
8. Thank them and say goodbye

## Rules
- ONLY sell items on the menu — if someone asks for something not listed, politely say you don't have it and suggest the closest alternative
- If you're unsure about something, ask the customer to repeat or clarify
- Keep responses concise — under 2 sentences when possible
- Do NOT make up prices or items
- DO NOT use any markdown, asterisks, bold, or formatting symbols in your responses — speak in plain, natural language only
- If the customer wants to cancel or start over, do it cheerfully
- Tell them the order will be ready in about 20 to 25 minutes

## Finalization
When the order is complete and confirmed by the customer, output this exact JSON on its own line:
{{"action":"order_complete","order":{{"customer_name":"...","customer_phone":"...","items":[{{"name":"Item Name","quantity":1,"price":9.99,"notes":"modifications"}}],"notes":"any special instructions","total":99.99}}}}

## Current Conversation
Keep track of what's been ordered so far. The customer may add items, remove items, or modify items at any point."""


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
        lines = [f'  - {item.name} (${item.price:.2f})']

        if item.modifiers:
            # Separate free choices (no +$) from paid add-ons (have +$)
            choices = []
            addons = []
            for m in item.modifiers:
                if '(+' in m:
                    # Extract price and clean up name
                    addons.append(m)
                else:
                    choices.append(m)

            if choices:
                lines.append(f'    Choice of: {", ".join(choices)}')
            if addons:
                lines.append(f'    Add-ons (extra charge): {", ".join(addons)}')

        if item.aliases:
            lines.append(f'    Aliases: {", ".join(item.aliases)}')

        categories[cat].append('\n'.join(lines))

    sections = []
    for cat, item_list in categories.items():
        sections.append(f'{cat}\n' + '\n'.join(item_list))

    return '\n\n'.join(sections)


def build_system_prompt():
    """Build the full system prompt with current menu."""
    restaurant_name = getattr(settings, 'RESTAURANT_NAME', 'Our Restaurant')
    menu_text = get_menu_text()
    return SYSTEM_PROMPT.format(restaurant_name=restaurant_name, menu_text=menu_text)


def get_client():
    """Get OpenAI async client."""
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def find_menu_matches(transcript: str, menu_items, threshold: float = 0.4) -> dict:
    """
    Fuzzy-match words in the customer's transcript against menu item names and aliases.

    Uses difflib.SequenceMatcher (Levenshtein-like) to catch STT mishearings
    like "kalsoy" → Khao Soi or "pep tai" → Pad Thai.

    Returns dict of {menu_item_name: (similarity_score, matched_word)}
    for every menu item with a score >= threshold, e.g.
    {"Khao Soi": (0.43, "kalsoy")}
    """
    # Build search index: (searchable_term_lower, menu_name)
    search_index = []
    for item in menu_items:
        search_index.append((item.name.lower(), item.name))
        for alias in getattr(item, 'aliases', []) or []:
            search_index.append((alias.lower(), item.name))

    # Generate candidates: individual words + consecutive bigrams
    # Skip very short words (<3 chars) to avoid spurious matches
    words = transcript.lower().split()
    candidates = {w for w in words if len(w) >= 3}
    for i in range(len(words) - 1):
        bigram = f'{words[i]} {words[i + 1]}'
        if len(bigram) >= 3:
            candidates.add(bigram)

    results = {}
    for candidate in candidates:
        best_menu = None
        best_score = 0.0
        for search_term, menu_name in search_index:
            score = difflib.SequenceMatcher(None, candidate, search_term).ratio()
            if score > best_score:
                best_score = score
                best_menu = menu_name
        if best_score >= threshold and best_menu:
            if best_menu not in results or best_score > results[best_menu][0]:
                results[best_menu] = (best_score, candidate)

    return results


class OrderAgent:
    """
    Manages a single phone conversation. Tracks conversation state,
    sends transcripts to OpenAI, and detects finalized orders.
    """

    def __init__(self):
        self.client = get_client()
        self.system_prompt = build_system_prompt()
        self.messages = []  # Conversation history (alternating user/assistant)
        self.order = None   # Will hold the extracted order dict when finalized
        # Pre-fetch menu items for fuzzy matching (constant within a call)
        from .models import MenuItem
        self._menu_items = list(MenuItem.objects.filter(available=True))

    async def process_transcript(self, text: str) -> str:
        """
        Send the customer's spoken text to OpenAI and get a response.

        Before sending, runs a fuzzy-matching pre-pass against menu items
        and injects hints for likely mispronunciations (e.g. "kalsoy" → Khao Soi).

        Returns the assistant's response text.
        If the response contains an order_complete action, self.order is set.
        """
        # Fuzzy match menu items — inject hints for likely mispronunciations
        matches = find_menu_matches(text, self._menu_items)
        if matches:
            hints = []
            for menu_name, (score, matched_word) in sorted(
                    matches.items(), key=lambda x: -x[1][0]):
                hints.append(f'    "{matched_word}" → {menu_name} (confidence: {score:.0%})')
            hint_text = '\n'.join(hints)
            logger.info(f'🔍 Menu fuzzy matches: {hint_text}')
            augmented = f'{text}\n\n(Hint: the customer may have mispronounced an item.\n{hint_text})'
        else:
            augmented = text

        self.messages.append({'role': 'user', 'content': augmented})

        # Build messages: system prompt + conversation history
        api_messages = [{'role': 'system', 'content': self.system_prompt}] + self.messages

        try:
            response = await self.client.chat.completions.create(
                model='gpt-4o-mini',
                max_tokens=300,
                messages=api_messages,
            )
        except Exception as e:
            logger.error(f'OpenAI API error: {e}')
            return "I'm sorry, I didn't quite catch that. Could you repeat it?"

        reply = response.choices[0].message.content.strip()
        reply = strip_markdown(reply)
        self.messages.append({'role': 'assistant', 'content': reply})

        # Trim conversation history to prevent unbounded growth and increasing latency.
        # Keep last 20 messages (10 turns). Older context is rarely needed for order-taking.
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]

        # Check if the model signaled order completion
        self._try_extract_order(reply)

        return reply

    def _try_extract_order(self, text: str):
        """Look for the order_complete JSON in the response."""
        try:
            # Find JSON block in the response
            start = text.find('{"action":"order_complete"')
            if start == -1:
                return

            # Find matching closing brace
            brace_count = 0
            end = start
            for i in range(start, len(text)):
                if text[i] == '{':
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break

            json_str = text[start:end]
            data = json.loads(json_str)

            if data.get('action') == 'order_complete':
                self.order = data.get('order', {})
                logger.info(f'Order extracted: {json.dumps(self.order, indent=2)}')

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f'Failed to parse order JSON: {e}')

    @property
    def is_order_complete(self):
        return self.order is not None


def save_order_from_agent(agent: OrderAgent, call_sid: str = ''):
    """
    Save the extracted order from the agent to the database and send SMS.
    """
    from .models import Order, OrderItem, MenuItem

    order_data = agent.order
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
