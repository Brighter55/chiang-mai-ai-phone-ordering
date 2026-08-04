# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI phone ordering system for Chiang Mai Thai Restaurant (St. Louis). A Twilio number forwards to the restaurant; when no one picks up, an AI assistant takes the order conversationally and sends it via SMS. Stack: Django 5 + Channels (ASGI/Daphne) + OpenAI GPT-4o-mini + Deepgram (Nova-2 STT, Aura TTS) + Twilio Voice/SMS.

## Commands

All commands run from the repo root on Windows (PowerShell). Python lives in `venv\`.

```powershell
# Install dependencies
.\venv\Scripts\pip install -r requirements.txt

# Migrate + seed the menu (seed_menu upserts from SAMPLE_MENU and deletes stale items)
.\venv\Scripts\python manage.py migrate
.\venv\Scripts\python manage.py seed_menu

# Run the server — use `python -m daphne`, NOT the daphne.exe shim,
# which fails silently with exit code 1 on this machine
.\venv\Scripts\python -m daphne -p 8000 -b 0.0.0.0 config.asgi:application

# Tests (orders/tests.py is currently empty — no real tests exist yet)
.\venv\Scripts\python manage.py test orders

# Full local test environment (daphne + ngrok + log tail) — custom skill
/start-testing-env
```

The `/start-testing-env` skill launches Daphne, an ngrok tunnel, and a log monitor. After starting, update the Twilio number's webhook to the new ngrok URL.

## Architecture

### Call flow

```
Twilio call → POST /twilio/voice/ → TwiML <Connect><Stream url="ws(s)://host/ws/call/">
    → CallConsumer (WebSocket, one instance per call)
        → DeepgramSTT (streaming WebSocket, nova-3-general via env, 8kHz mulaw, menu keyterms)
        → OrderAgent (OpenAI gpt-4o-mini)
        → Deepgram Aura TTS (HTTP POST, inline in consumer) → audio frames back to Twilio
    → order complete → save_order_from_agent → send_order_sms → hangup via Twilio REST
```

### Key files

- `config/asgi.py` — `ProtocolTypeRouter`: HTTP → Django, WebSocket → `orders/routing.py` (`/ws/call/`). Server must run under Daphne (ASGI), not `runserver`.
- `orders/views.py` — Twilio webhooks: `twilio_voice_webhook` (returns the Stream TwiML; builds ws/wss URL from the request host) and `twilio_sms_status`. Both `@csrf_exempt`. Real paths are `/twilio/voice/` and `/twilio/sms-status/` (mounted under `twilio/` in `config/urls.py`).
- `orders/consumers.py` — `CallConsumer`, the core pipeline. Lifecycle: `connect` → `receive` (media loop) → `disconnect`. See "Key mechanisms" below.
- `orders/stt.py` — `DeepgramSTT` wrapper: async connect, sync `send_audio`, JSON `KeepAlive` every 5s to beat Deepgram's ~10s idle timeout, `endpointing=300`ms. Model from `DEEPGRAM_STT_MODEL` env (default `nova-3-general`); `keyterm` biases decoding toward menu vocabulary (`build_keyterms`). Callback `on_transcript` fires on `speech_final` transcripts.
- `orders/agent.py` — `OrderAgent` builds the system prompt **per call** from `SYSTEM_PROMPT.format(menu_text=get_menu_text())` where menu text comes from the DB (includes aliases as "Pronunciations:" lines). Also: `build_keyterms` (curated menu vocabulary fed to STT keyterm biasing), `strip_markdown`, `strip_order_json`, `save_order_from_agent`.
- `orders/notify.py` — `get_twilio_client`, `send_order_sms` (formatted SMS; on failure logs content and leaves `sms_sent=False` for retry).
- `orders/tts.py` — legacy Twilio `<Say>` helper; `text_to_media_stream_audio` raises NotImplementedError. Real TTS lives inline in `CallConsumer._speak_response` (Deepgram HTTP API, mulaw/8kHz, streamed in 160-byte/20ms frames).

### Key mechanisms (consumer)

- **Echo filtering**: while `is_speaking`, incoming audio is not sent to STT (barge-in disabled by default — echo makes it unreliable on phone calls; `_barge_in_enabled` gates the whole path). Transcripts arriving during speech are dropped in `_on_transcript`.
- **Silence nudging**: `_process_transcripts` waits on a transcript queue; after 8s of silence (`NUDGE_TIMEOUT`) it nudges ("didn't catch that"), and after 2 unanswered nudges (`MAX_NUDGES`) says goodbye and hangs up. The nudge timer starts only after the greeting finishes (`greeting_done` event).
- **Order completion contract**: the system prompt instructs the model to end its final message with an exact `{"action":"order_complete",...}` JSON block on its own line. `_try_extract_order` scans for it; `strip_order_json` removes it before TTS so it's never spoken. Without it, no DB save, no SMS, no hangup. Conversation history is trimmed to the last 20 messages.
- **Threading**: all ORM work runs through `sync_to_async(..., thread_sensitive=False)` — `OrderAgent` init, order save + SMS, and the Twilio hangup. OpenAI/Deepgram/Twilio HTTP calls are async.
- **Timing**: `_timings` dict logs per-stage averages (openai, tts_total, turn_total) on disconnect.
- **Hangup**: after order finalization, waits 0.5s, calls Twilio REST `status=completed`, closes the WebSocket.

## Menu data & conventions

- `orders/management/commands/seed_menu.py` holds the canonical `SAMPLE_MENU` (91 items). The command upserts by name and deletes items no longer listed. `chiang_mai_menu.xlsx` is the original data source.
- `MenuItem.modifiers` is a JSON list with a **format contract** that `get_menu_text` (agent.py) parses into prompt sections:
  - `'N - label'` (e.g. `'0 - no spice'`) → "Spice level:" line
  - contains `'(+$X)'` (e.g. `'add chicken (+$3.09)'`) → "Add-ons (extra charge):" — paid
  - anything else (e.g. `'chicken'`, `'broccoli'`) → "Choice of:" — free
  - Keep this format when editing menu items; the AI's pricing rules in `SYSTEM_PROMPT` depend on it (free choices vs paid add-ons).
- `aliases` hold phonetic variants ("kalsoy" → Khao Soi). They feed two things: the STT `keyterm` list (`build_keyterms`) and the prompt's "Pronunciations:" lines. Adding aliases like `garlic moo` for Gra Dook Moo fixes Thai-English phrase recognition.

## Configuration

- `.env` (gitignored) is loaded via `python-dotenv` in `config/settings.py`. Copy `.env.example`. Keys: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `DEEPGRAM_STT_MODEL` (default `nova-3-general`), `DEEPGRAM_TTS_MODEL` (default `aura-asteria-en`), `DEEPGRAM_TTS_RATE` (default `1.2`), `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `RESTAURANT_PHONE`, `RESTAURANT_NAME`.
- DB defaults to PostgreSQL via env vars (`DB_NAME`, `DB_USER`, ...); channel layer is in-memory (dev only).
- Logging: console INFO; `orders` and `daphne` loggers. Emoji-prefixed log lines (`🎙`, `🔇`, `⏱`) mark call pipeline stages.
- Deployment: `render.yaml` blueprint — Daphne start command, `migrate` pre-deploy.

## Testing locally with a real call

1. `/start-testing-env` (daphne + ngrok + log tail)
2. Point the Twilio number's voice webhook at `https://<ngrok-url>/twilio/voice/`
3. Call the number; watch the log monitor for STT transcripts, AI responses, and TTS timing
