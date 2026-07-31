"""
Conversation agent using OpenAI for restaurant order taking.
"""
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


def strip_order_json(text: str) -> str:
    """Remove the order_complete JSON block from text before TTS speaks it."""
    # Remove the order_complete JSON object — it's for the system, not the customer's ears
    # Matches {"action":"order_complete",...} including nested braces
    pattern = r'\n?\{\s*"action"\s*:\s*"order_complete".*?\}\s*$'
    return re.sub(pattern, '', text, flags=re.DOTALL).strip()


# System prompt template — menu is injected at call time
SYSTEM_PROMPT = """You are an AI phone order taker for {restaurant_name}. You take food orders over the phone.

## Your Role
- Be friendly, warm, and efficient — like a great server
- Take orders conversationally, one step at a time
- Confirm each item before moving on
- Suggest popular items or upsells naturally when appropriate
- Always repeat the full order before finalizing
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

"Choice of:" — FREE options included in the base price:
- Some items list proteins (chicken, tofu, vegetables, shrimp) — for those items, the customer picks one at no extra charge.
- Some items list vege types (broccoli vs Asian green veggies) — ask which they prefer.
- If there is NO "Choice of:" line, the dish comes as described — do NOT ask about protein or other choices.

"Spice level:" — shown as a number scale (0 to 5). ALWAYS ask which number they want.

"Add-ons (extra charge):" — these cost extra and are for customers who want ADDITIONAL protein, vegetables, or modifications beyond what's standard.

Examples of correct pricing:
- Pad Thai ($17.59) with chicken = $17.59 (chicken is in "Choice of:", no extra charge)
- Pad Thai ($17.59) with extra chicken = $20.68 (base $17.59 + add chicken $3.09)
- Pad Thai ($17.59) with tofu = $17.59 (tofu is in "Choice of:", no extra charge)
- Khao Soi ($17.59) = $17.59 (Khao Soi always comes with chicken drumsticks — no protein choice in "Choice of:")
- Khao Soi ($17.59) with extra chicken = $20.68 (customer wants extra as a paid add-on)
- Do NOT tell customers that choosing chicken adds $3 — it only adds $3 if they ask for EXTRA chicken

## Order Flow
1. Greet the customer: "Thank you for calling {restaurant_name}. All our staff are currently busy assisting other customers, but I can take your order right away. What can I get for you today?"
2. Take their order item by item.
   - If the item has a "Spice level:" line, ALWAYS ask "how spicy would you like it, on a scale from 0 to 5?" (0 = no spice, 5 = spiciest). Use the NUMBER, don't list the words.
   - If it has a "Choice of:" line with proteins, ask which protein they'd like — it's included in the base price.
   - If it has a "Choice of:" line with veggie types (broccoli vs Asian green veggies), ask which they prefer.
   - If there is NO "Choice of:" line at all, do NOT ask about protein or veggie choices. The dish comes as described. You may still mention available paid add-ons if the customer seems interested.
   - For items with BOTH spice level and Choice of, ask about the spice level first, then the choice.
3. After each item, confirm what you heard
4. Suggest add-ons or popular items naturally (one suggestion max)
5. When they're done, read back the full order with prices
6. Ask for their name — just their name, nothing else
7. After they give you their name, then ask for a callback phone number
8. Give them a total and estimated time
9. In your final message: say goodbye naturally, then output the JSON (see Finalization below) on its own line — this triggers the hang-up. Do NOT forget the JSON.

## Rules
- ONLY sell items on the menu — if someone asks for something not listed, politely say you don't have it and suggest the closest alternative
- If you're unsure about something, ask the customer to repeat or clarify
- Keep responses concise — under 2 sentences when possible
- Do NOT make up prices or items
- DO NOT use any markdown, asterisks, bold, or formatting symbols in your responses — speak in plain, natural language only
- If the customer wants to cancel or start over, do it cheerfully
- Tell them the order will be ready in about 20 to 25 minutes

## Finalization — CRITICAL — READ CAREFULLY
In your FINAL goodbye message you MUST include the JSON below on its own line at the END. The system strips this JSON before TTS — the customer will NEVER hear it; only the system sees it to trigger hang-up and save the order.

Output this EXACT JSON on its own line at the END of your final message:
{{"action":"order_complete","order":{{"customer_name":"Customer Name","customer_phone":"555-123-4567","items":[{{"name":"Item Name","quantity":1,"price":9.99,"notes":"spice level 5, with chicken"}}],"notes":"","total":9.99}}}}

Example final message — the JSON after the goodbye is silent, only spoken part is above it:
"Thank you Peter, your Pad Thai with shrimp at spice level five comes to $17.59 total. It'll be ready in 20 to 25 minutes. Have a great day!
{{"action":"order_complete","order":{{"customer_name":"Peter","customer_phone":"314-954-6598","items":[{{"name":"Pad Thai","quantity":1,"price":17.59,"notes":"spice level 5, shrimp"}}],"notes":"","total":17.59}}}}

Without this JSON the call will NOT hang up, order will NOT save, SMS will NOT send.

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
        # Include Thai name in the menu listing for cross-lingual matching
        if item.thai_name:
            lines = [f'  - {item.name} — {item.thai_name} — ${item.price:.2f}']
        else:
            lines = [f'  - {item.name} — ${item.price:.2f}']

        if item.modifiers:
            # Separate spice levels, free choices (no +$), and paid add-ons (have +$)
            spice_levels = []
            choices = []
            addons = []
            for m in item.modifiers:
                if '(+' in m:
                    addons.append(m)
                elif re.match(r'^\d\s*-\s', m):
                    spice_levels.append(m)
                else:
                    choices.append(m)

            if spice_levels:
                lines.append(f'    Spice level: 0 (none) to 5 (extra hot) — pick a number')
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


def build_system_prompt():
    """Build the full system prompt with current menu."""
    restaurant_name = getattr(settings, 'RESTAURANT_NAME', 'Our Restaurant')
    menu_text = get_menu_text()
    return SYSTEM_PROMPT.format(restaurant_name=restaurant_name, menu_text=menu_text)


def get_client():
    """Get OpenAI async client."""
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _metaphone(text: str) -> str:
    """Get Double Metaphone phonetic encoding for a string.

    Returns the primary metaphone code, which represents how the word sounds.
    Words that sound similar (e.g. "cow soy" and "khao soi") get similar codes.
    Returns empty string for unencodable input.
    """
    try:
        import jellyfish
        return jellyfish.metaphone(text) or ''
    except ImportError:
        return ''


def find_menu_matches(transcript: str, menu_items, threshold: float = 0.6) -> dict:
    """
    Phonetic-match words in the customer's transcript against menu item names,
    aliases, and Thai names using Double Metaphone.

    Unlike difflib (which compares character-level spelling), Double Metaphone
    encodes words by how they sound — so "cow soy" matches "Khao Soi" even
    though they share almost no letters in common.

    Returns dict of {menu_item_name: (similarity_score, matched_word)}
    for every menu item with a score >= threshold, e.g.
    {"Khao Soi": (0.85, "cow soy")}
    """
    # Build search index with pre-computed metaphone codes.
    # Each entry: (metaphone_code, menu_name, original_search_term)
    search_index = []
    for item in menu_items:
        # Index item name
        name_meta = _metaphone(item.name)
        if name_meta:
            search_index.append((name_meta, item.name, item.name))

        # Index Thai name
        thai_name = getattr(item, 'thai_name', '') or ''
        if thai_name:
            thai_meta = _metaphone(thai_name)
            if thai_meta:
                search_index.append((thai_meta, item.name, thai_name))

        # Index all aliases
        for alias in getattr(item, 'aliases', []) or []:
            alias_meta = _metaphone(alias)
            if alias_meta:
                search_index.append((alias_meta, item.name, alias))

    # Generate candidates: individual words + consecutive bigrams + trigrams
    # Skip very short words (<3 chars) to avoid spurious matches
    words = transcript.lower().split()
    candidates = {w for w in words if len(w) >= 3}
    for i in range(len(words) - 1):
        bigram = f'{words[i]} {words[i + 1]}'
        if len(bigram) >= 3:
            candidates.add(bigram)
    for i in range(len(words) - 2):
        trigram = f'{words[i]} {words[i + 1]} {words[i + 2]}'
        if len(trigram) >= 3:
            candidates.add(trigram)

    results = {}
    for candidate in candidates:
        cand_meta = _metaphone(candidate)
        if not cand_meta:
            continue

        best_menu = None
        best_score = 0.0
        for search_meta, menu_name, _search_term in search_index:
            if not search_meta:
                continue

            # Primary: exact metaphone match → perfect phonetic hit
            if cand_meta == search_meta:
                score = 1.0
            else:
                # Secondary: metaphone codes are similar but not identical
                # Use string similarity on the metaphone codes themselves
                # (metaphone codes are short ASCII, so this is fast)
                if len(cand_meta) <= 2 or len(search_meta) <= 2:
                    continue  # too short to compare meaningfully
                score = _code_similarity(cand_meta, search_meta)
                if score < 0.7:
                    continue  # not phonetically close enough

            if score > best_score:
                best_score = score
                best_menu = menu_name

        if best_score >= threshold and best_menu:
            if best_menu not in results or best_score > results[best_menu][0]:
                results[best_menu] = (best_score, candidate)

    return results


def _code_similarity(a: str, b: str) -> float:
    """Simple similarity between two metaphone code strings.

    Uses a combination of prefix match and length-normalized edit distance.
    Metaphone codes are short (typically 4-8 chars), so this is very fast.
    """
    # Prefix matching: "KS" vs "KSL" should score high
    min_len = min(len(a), len(b))
    if min_len == 0:
        return 0.0

    # Count matching characters in the shorter string
    matches = sum(1 for i in range(min_len) if a[i] == b[i])
    prefix_score = matches / min_len

    # Also check if one code is a substring of the other
    substring_bonus = 0.2 if (a in b or b in a) else 0.0

    return min(1.0, prefix_score + substring_bonus)


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

        Before sending, runs a phonetic-matching pre-pass against menu items
        and injects hints for likely mispronunciations (e.g. "cow soy" → Khao Soi).

        Returns the assistant's response text.
        If the response contains an order_complete action, self.order is set.
        """
        # Phonetic match menu items — inject hints for likely mispronunciations
        matches = find_menu_matches(text, self._menu_items)
        if matches:
            hints = []
            for menu_name, (score, matched_word) in sorted(
                    matches.items(), key=lambda x: -x[1][0]):
                hints.append(f'    "{matched_word}" → {menu_name} (phonetic match: {score:.0%})')
            hint_text = '\n'.join(hints)
            logger.info(f'🔍 Menu phonetic matches: {hint_text}')
            augmented = f'{text}\n\n(Hint: the customer may have said a menu item — match on sound, not spelling:\n{hint_text})'
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
