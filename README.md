# Chiang Mai AI — AI Phone Ordering System

An AI-powered phone ordering system for **Chiang Mai Thai Restaurant** in St. Louis, Missouri. Customers call the restaurant's number; if the restaurant doesn't pick up, an AI assistant answers, takes the order conversationally, and **pushes it straight to the restaurant's Clover POS** as an open "Take out" ticket — with a formatted SMS to the restaurant phone as a backup.

Built with **Django + Django Channels + the Deepgram Voice Agent API** (managed speech-to-text, LLM, and text-to-speech in one WebSocket) **+ Twilio Voice/SMS + Clover POS**.

## How It Works

1. **Customer calls** the restaurant's Twilio number
2. **AT&T call forwarding** rings the restaurant first; the AI only answers if no one picks up
3. **AI takes the order** — speaks naturally, asks about spice levels, protein/veggie choices, and add-ons, and briefly confirms each item
4. **AI answers practical questions** — location, hours, and pickup details, straight from a "quick facts" section in its prompt
5. **Order goes to the kitchen** — saved locally, pushed to Clover as an open ticket, and texted to the restaurant as a backup; special requests (e.g. "no vegetables") print as notes on the ticket
6. **Call hangs up on its own** — a few seconds after the agent finishes its goodbye
7. **Talk to a human?** — callers who ask for a staff member are cold-transferred to a configured staff line

## Feature Highlights

- **🎙 Natural conversation** — Deepgram's managed Voice Agent handles listening, thinking, speaking, turn-taking, and barge-in; the server just relays audio and handles function calls
- **🗣 Thai-menu-aware speech** — Nova-3 STT biased with curated phonetic keyterms ("cow soy" → Khao Soi); menu items carry Thai script and aliases so the agent matches both Thai and English pronunciations
- **🍜 Ask only what the dish lists** — spice level (0–5) only where the menu entry shows one, protein/veggie choices only where there's a "Choice of", paid add-ons only when offered
- **📋 Kitchen-ready tickets** — special requests land in Clover line-item notes; free choices, paid alternatives, and paid add-ons are priced correctly
- **📞 Transfer to human** — optional, guarded against forwarding loops and toll fraud
- **🛎 Hang-up you can rely on** — the call ends server-side shortly after the order is placed, without trusting the model to call "end the call"
- **🛠 Django admin** — full order history and menu management at `/admin/`

## Architecture

```
Twilio Voice ──► POST /twilio/voice/ ──► TwiML <Connect><Stream>
                        │
                 WebSocket (Django Channels, /ws/call/)
                        │
                    CallConsumer ──► Deepgram Voice Agent API
                        │        (one managed WebSocket: audio relay + function calls)
                        ▼
          place_order → local Order/OrderItem (DB)
                        ├──► SMS to restaurant phone (backup)
                        └──► Clover POS — open "Take out" ticket (primary)
```


## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.x |
| WebSocket | Django Channels + Daphne (ASGI) |
| Voice agent | Deepgram Voice Agent API — Nova-3 STT · GPT-4o-mini LLM · Aura TTS (temp 0) |
| Telephony / SMS | Twilio |
| Point of Sale | Clover REST v3 (`atomic_order`, Bearer token) |
| Database | PostgreSQL (prod) / PostgreSQL local |
| Deployment | Render (`render.yaml`) |

## Getting Started

### Prerequisites

- Python 3.11+
- A Twilio account with a voice-enabled phone number
- A Deepgram API key (Voice Agent access)
- A Clover merchant API token (optional — the system runs on SMS-only without it)
- PostgreSQL

### Setup

1. **Clone and create a virtual environment:**

   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   source venv/bin/activate  # macOS/Linux
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**

   ```bash
   cp .env.example .env
   ```

   Fill in your keys in `.env`. The important ones:

   | Variable | Description |
   |----------|-------------|
   | `DEEPGRAM_API_KEY` | Your Deepgram API key (Voice Agent) |
   | `DEEPGRAM_VOICE_AGENT_STT_MODEL` | Default `nova-3-general` — must stay Nova-3 for Thai keyterms |
   | `DEEPGRAM_VOICE_AGENT_LLM_MODEL` | Default `gpt-4o-mini` |
   | `DEEPGRAM_VOICE_AGENT_TTS_MODEL` | Default `aura-asteria-en` |
   | `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Twilio API credentials |
   | `TWILIO_PHONE_NUMBER` | Your Twilio number (+1...) |
   | `RESTAURANT_PHONE` | Restaurant phone for SMS order backup |
   | `RESTAURANT_NAME` | Default: "Our Restaurant" |
   | `TRANSFER_PHONE` | *(optional)* Direct staff line to transfer callers to; empty disables transfers |
   | `CLOVER_MERCHANT_ID` / `CLOVER_API_TOKEN` | *(optional)* Push orders to Clover as open tickets |
   | `CLOVER_BASE_URL` | `https://api.clover.com` (sandbox: `https://apisandbox.dev.clover.com`) |
   | `CLOVER_ORDER_TYPE_NAME` | Default `Take out` (must exist in the merchant) |

4. **Run migrations and load the menu.** Choose one menu source (they're alternatives):

   ```bash
   python manage.py migrate
   python manage.py seed_menu                # 65-item built-in menu (offline / fallback)
   python manage.py sync_menu_from_clover    # pull from Clover (source of truth in prod)
   ```

   `sync_menu_from_clover` preserves curated phonetic aliases and Thai names; try `--dry-run` first, and use `--seed-aliases` to copy aliases for brand-new items.

5. **Create a Django admin user:**

   ```bash
   python manage.py createsuperuser
   ```

6. **Start the server** (ASGI — Daphne is required):

   ```bash
   python -m daphne -p 8000 -b 0.0.0.0 config.asgi:application
   ```

7. **Expose with ngrok** (so Twilio can reach your webhooks):

   ```bash
   ngrok http 8000
   ```

8. **Configure your Twilio number:**
   - Voice webhook: `https://your-ngrok-url.ngrok.io/twilio/voice/`
   - SMS status callback: `https://your-ngrok-url.ngrok.io/twilio/sms-status/`

## How an Order Reaches the Kitchen

1. The agent matches what the caller says to a menu item using **sound matching** ("cow soy" → Khao Soi), **Thai names** (ข้าวซอย), or **descriptions** ("the curry noodle soup").
2. For each item it asks only the questions that item's menu entry lists — a 0–5 **spice level**, a **protein/veggie choice**, and optional **paid add-ons** — and won't confirm or place an item until each is answered (it picks and confirms a sensible default if the caller won't).
3. Non-option requests — "no vegetables", "extra sauce on the side" — go into that item's **notes**, not its modifiers, so they aren't mistaken for a real menu option.
4. Once the caller signals they're done, the agent collects the name and a callback number, reads back the total, then calls `place_order`.
5. The order is saved locally, **texted** to the restaurant phone, and **pushed to Clover** as an open "Take out" ticket (each quantity expanded to its own line, paid options resolved to Clover modifiers, notes attached to the line item). A Clover outage never blocks the call — failed pushes are recorded on the order for a manual retry.
6. After the agent's goodbye, the system hangs up on its own. If the caller asked for a human at any point, they're cold-transferred to `TRANSFER_PHONE` instead, and the announcement/apology is handled by Twilio TwiML.

## Menu

The system ships with **Chiang Mai's full menu (65 items)** across categories:

- Small Plates (Gai Todd, Som Tum, Poh Piah, etc.)
- Entrees (Pad Thai, Khao Soi, Drunken Noodles, Pad See Ew, etc.)
- Authentic Thai Curries (Kaeng Daeng, Massaman Beef, Yellow Curry, etc.)
- Noodle Soups · Beverages · NA Beverages
- Specials (Mango Sticky Rice) · Side Orders

Items include **phonetic aliases** ("kalsoy" → Khao Soi) and **Thai script names** so the agent and the speech engine recognize how real customers pronounce dishes. In production the menu is synced from Clover, so names and prices always match what's in the POS.

## Project Structure

```
chiang-mai-ai/
├── config/               # Django project configuration
│   ├── settings.py       # Settings, env vars, ASGI config
│   └── asgi.py           # HTTP + WebSocket ASGI routing
├── orders/               # Main application
│   ├── models.py         # MenuItem, Order, OrderItem (+ Clover id fields)
│   ├── consumers.py      # WebSocket consumer — audio relay + function calls + hangup
│   ├── agent.py          # Voice Agent settings, prompt, keyterms, order persistence
│   ├── clover.py         # Clover POS client: menu sync + atomic-order push
│   ├── transfer.py       # Transfer-to-human helpers + prompt blocks
│   ├── views.py          # Twilio webhook endpoints (voice / transfer-result / sms-status)
│   ├── notify.py         # SMS order notification
│   ├── tests.py          # Transfer feature tests
│   ├── admin.py          # Django admin configuration
│   ├── routing.py        # WebSocket URL routing
│   └── management/commands/
│       ├── seed_menu.py            # Built-in 65-item menu seeder
│       ├── sync_menu_from_clover.py# Sync menu from Clover catalog
│       └── push_order_to_clover.py # Manually re-push an order to Clover
├── _dg_va_prompt.txt     # Tested system prompt (git-tracked; live menu injected)
├── _dg_keyterms.txt      # Curated STT phonetic keyterms (git-tracked)
├── manage.py
├── requirements.txt
├── .env.example
└── render.yaml           # Render deployment blueprint
```

## Management Commands

| Command | Purpose |
|---------|---------|
| `seed_menu` | Upsert the 65-item built-in menu (deletes anything not in it — don't run against a Clover-synced menu) |
| `sync_menu_from_clover` | Pull names/prices/modifiers from Clover; preserves aliases & Thai names (`--dry-run`, `--seed-aliases`, `--delete-missing`) |
| `push_order_to_clover <id>` | Manually re-push a local order after a failed push (`--force` to re-push) |
| `test orders` | Run the transfer-feature test suite |

## Deployment

The project includes a `render.yaml` blueprint: connect the repo to Render, set the API keys and Clover/transfer env vars, and it deploys with Daphne ASGI and a `migrate` pre-deploy step. The git-tracked prompt and keyterm files ship with the repo, so production uses the same tested system prompt (with the live menu injected from the database).

## Testing Locally with a Real Call

Run the `/start-testing-env` skill (Daphne + ngrok + a log monitor), point your Twilio voice webhook at `https://<ngrok-url>/twilio/voice/`, then call the number and watch the log for `USER:`/`ASSISTANT:` transcripts, function calls, and the Clover/SMS push.

## License

Private — Chiang Mai Thai Restaurant internal use.
