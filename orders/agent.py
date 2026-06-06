"""
Conversation agent using Claude Haiku 4.5 for restaurant order taking.
"""

import json
import logging
from django.conf import settings
from anthropic import Anthropic

logger = logging.getLogger(__name__)

# System prompt template — menu is injected at call time
SYSTEM_PROMPT = """You are an AI phone order taker for {restaurant_name}. You take food orders over the phone.

## Your Role
- Be friendly, warm, and efficient — like a great server
- Take orders conversationally, one step at a time
- Confirm each item before moving on
- Suggest popular items or upsells naturally when appropriate
- Always repeat the full order before finalizing

## The Menu
{menu_text}

## Order Flow
1. Greet the customer: "Thank you for calling {restaurant_name}, this is AI order assistant. What can I get for you today?"
2. Ask if this is for pickup or delivery
3. Take their order item by item — ask about modifications where relevant
4. After each item, confirm what you heard
5. Suggest add-ons or popular items naturally (one suggestion max)
6. When they're done, read back the full order with prices
7. Ask for their name and a callback phone number
8. Give them a total and estimated time
9. Thank them and say goodbye

## Rules
- ONLY sell items on the menu — if someone asks for something not listed, politely say you don't have it and suggest the closest alternative
- If you're unsure about something, ask the customer to repeat or clarify
- Keep responses concise — under 2 sentences when possible
- Do NOT make up prices or items
- If the customer wants to cancel or start over, do it cheerfully
- For pickup orders: tell them the order will be ready in about 20-25 minutes
- For delivery orders: tell them delivery typically takes 30-45 minutes

## Finalization
When the order is complete and confirmed by the customer, output this exact JSON on its own line:
{{"action":"order_complete","order":{{"customer_name":"...","customer_phone":"...","order_type":"pickup or delivery","items":[{{"name":"Item Name","quantity":1,"price":9.99,"notes":"modifications"}}],"notes":"any special instructions","total":99.99}}}}

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
        modifier_str = ''
        if item.modifiers:
            modifier_str = ' [' + ', '.join(item.modifiers) + ']'
        categories[cat].append(f'  - {item.name} (${item.price:.2f}){modifier_str}')

    sections = []
    for cat, item_list in categories.items():
        sections.append(f'### {cat}\n' + '\n'.join(item_list))

    return '\n\n'.join(sections)


def build_system_prompt():
    """Build the full system prompt with current menu."""
    restaurant_name = getattr(settings, 'RESTAURANT_NAME', 'Our Restaurant')
    menu_text = get_menu_text()
    return SYSTEM_PROMPT.format(restaurant_name=restaurant_name, menu_text=menu_text)


def get_client():
    """Get Anthropic client."""
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


class OrderAgent:
    """
    Manages a single phone conversation. Tracks conversation state,
    sends transcripts to Claude Haiku, and detects finalized orders.
    """

    def __init__(self):
        self.client = get_client()
        self.system_prompt = build_system_prompt()
        self.messages = []  # Conversation history (alternating user/assistant)
        self.order = None  # Will hold the extracted order dict when finalized

    async def process_transcript(self, text: str) -> str:
        """
        Send the customer's spoken text to Claude and get a response.

        Returns the assistant's response text.
        If the response contains an order_complete action, self.order is set.
        """
        self.messages.append({'role': 'user', 'content': text})

        try:
            response = self.client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=300,
                system=self.system_prompt,
                messages=self.messages,
            )
        except Exception as e:
            logger.error(f'Claude API error: {e}')
            return "I'm sorry, I didn't quite catch that. Could you repeat it?"

        reply = response.content[0].text.strip()
        self.messages.append({'role': 'assistant', 'content': reply})

        # Check if Claude signaled order completion
        self._try_extract_order(reply)

        return reply

    def _try_extract_order(self, text: str):
        """Look for the order_complete JSON in Claude's response."""
        try:
            # Find JSON block in the response
            start = text.find('{"action":"order_complete"')
            if start == -1:
                return

            # Extract just the JSON part
            end = text.find('}', start)
            # Find matching closing brace
            brace_count = 0
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
        order_type=order_data.get('order_type', 'pickup'),
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
