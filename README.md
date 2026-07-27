# Chiang Mai AI — AI Phone Ordering System

An AI-powered phone ordering system for **Chiang Mai Thai Restaurant** in St. Louis, Missouri. Customers call the restaurant's number; if the restaurant doesn't pick up, an AI assistant takes the order conversationally and sends it via SMS.

Built with **Django + Django Channels + OpenAI GPT-4o-mini + Deepgram STT/TTS + Twilio Voice/SMS**.

## How It Works

1. **Customer calls** the restaurant's Twilio number
2. **AT&T call forwarding** rings the restaurant first; the AI only answers if no one picks up
3. **AI takes the order** — speaks naturally, asks about spice levels, protein choices, and add-ons
4. **Order is confirmed** — AI reads back the full order with prices
5. **SMS notification** — formatted order text sent to the restaurant phone
6. **Call hangs up** — automatically after the order is saved

## Architecture

```
Twilio Voice ──► Django Webhook ──► TwiML with Stream URL
                        │
                    WebSocket (Django Channels)
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
       Deepgram     OpenAI      Deepgram
         STT      GPT-4o-mini     TTS
      (Nova-2)     (Agent)     (Aura-Asteria)
            │           │           │
            └───────────┼───────────┘
                        ▼
              Save to DB ──► SMS to Restaurant
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.x + DRF |
| WebSocket | Django Channels + Daphne (ASGI) |
| LLM | OpenAI GPT-4o-mini |
| Speech-to-Text | Deepgram Nova-2 Phonecall |
| Text-to-Speech | Deepgram Aura Asteria |
| Voice / SMS | Twilio |
| Database | PostgreSQL (prod) / SQLite (dev) |
| Deployment | Render |

## Getting Started

### Prerequisites

- Python 3.11+
- A Twilio account with a voice-enabled phone number
- A Deepgram API key
- An OpenAI API key
- PostgreSQL (optional — SQLite works for dev)

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

   Fill in your API keys in `.env`:

   | Variable | Description |
   |----------|-------------|
   | `OPENAI_API_KEY` | Your OpenAI API key |
   | `DEEPGRAM_API_KEY` | Your Deepgram API key |
   | `TWILIO_ACCOUNT_SID` | Twilio account SID |
   | `TWILIO_AUTH_TOKEN` | Twilio auth token |
   | `TWILIO_PHONE_NUMBER` | Your Twilio phone number (+1...) |
   | `RESTAURANT_PHONE` | Restaurant phone for SMS orders |
   | `RESTAURANT_NAME` | Default: "Chiang Mai" |

4. **Run migrations and seed the menu:**

   ```bash
   python manage.py migrate
   python manage.py seed_menu
   ```

5. **Create a Django admin user:**

   ```bash
   python manage.py createsuperuser
   ```

6. **Start the server:**

   ```bash
   daphne config.asgi:application -p 8000 -b 0.0.0.0
   ```

7. **Expose with ngrok** (for Twilio webhook):

   ```bash
   ngrok http 8000
   ```

8. **Configure your Twilio number:**
   - Set the voice webhook to: `https://your-ngrok-url.ngrok.io/twilio/voice/`
   - Set the SMS status callback to: `https://your-ngrok-url.ngrok.io/twilio/sms-status/`

## Menu

The system comes seeded with **Chiang Mai's full menu** (91 items) across categories:

- Small Plates (Gai Todd, Som Tum, Steamed Dumplings, etc.)
- Entrees (Pad Thai, Khao Soi, Drunken Noodles, etc.)
- Authentic Thai Curries (Kaeng Daeng, Massaman Beef, etc.)
- Noodle Soups
- Beverages (beer, wine, sake, spirits)
- NA Beverages (Thai iced tea/coffee, sodas, juice)
- Specials (Mango Sticky Rice)
- Side Orders

Items include **phonetic aliases** for STT robustness — e.g., "kalsoy" → Khao Soi, "pep tai" → Pad Thai.

## Project Structure

```
chiang-mai-ai/
├── config/               # Django project configuration
│   ├── settings.py       # Settings, API keys, ASGI config
│   └── asgi.py           # HTTP + WebSocket ASGI routing
├── orders/               # Main application
│   ├── models.py         # MenuItem, Order, OrderItem
│   ├── consumers.py      # WebSocket consumer (audio pipeline)
│   ├── agent.py          # OpenAI conversation agent + fuzzy matching
│   ├── stt.py            # Deepgram STT streaming client
│   ├── tts.py            # TTS abstraction layer
│   ├── views.py          # Twilio webhook endpoints
│   ├── notify.py         # SMS notification
│   ├── admin.py          # Django admin configuration
│   ├── routing.py        # WebSocket URL routing
│   └── management/
│       └── commands/
│           └── seed_menu.py  # Menu data seeder
├── manage.py
├── requirements.txt
├── .env.example
└── render.yaml           # Render deployment blueprint
```

## Key Features

- **🎙 Natural conversation** — AI takes orders one item at a time, confirms each, asks about spice level (0–5 scale), protein choices, and add-ons
- **🔊 High-quality TTS** — Deepgram Aura Asteria produces natural-sounding speech; fallback to Twilio `<Say>` available
- **🗣 Fuzzy menu matching** — Handles mispronunciations by matching transcripts against menu names and aliases using Levenshtein similarity
- **📱 SMS delivery** — Order details sent to restaurant phone immediately after call ends
- **🛎 Call hang-up** — Automatic hang-up via Twilio REST API after order is saved
- **🔇 Markdown-free speech** — AI responses stripped of markdown artifacts before TTS
- **🛠 Django admin** — Full order history and menu management at `/admin/`

## Deployment

The project includes a `render.yaml` blueprint for Render. Connect your repo to Render, set the API keys as environment variables, and it deploys out of the box with Daphne ASGI.

## Cost

Estimated **~$80/month** at 20 calls/day, ~3 min each. Well under the $100 budget.
- Twilio: ~$33 (phone + voice + SMS)
- Deepgram: ~$38 (STT + TTS)
- OpenAI: ~$2 (GPT-4o-mini)
- Hosting: ~$7 (Render)

## License

Private — Chiang Mai Thai Restaurant internal use.
