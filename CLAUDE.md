# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI phone ordering system for Chiang Mai Thai Restaurant (St. Louis). A Twilio number forwards to the restaurant; when no one picks up, an AI assistant takes the order conversationally and sends it via SMS. Stack: Django 5 + Channels (ASGI/Daphne) + **Deepgram Voice Agent API** (managed STT + LLM + TTS in one WebSocket) + Twilio Voice/SMS.

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
    → CallConsumer (WebSocket, one instance per call) — thin audio relay
        → Deepgram Voice Agent API (wss://agent.deepgram.com/v1/agent/converse)
            STT (nova-3-general, mulaw 8kHz, menu keyterms) + LLM (gpt-4o-mini, temp 0)
            + TTS (aura-asteria-en) + turn-taking + barge-in — all managed server-side
    → agent calls `place_order` → save_order_from_agent → send_order_sms
    → agent calls `end_conversation` (or socket closes) → hangup via Twilio REST
```

### Key files

- `config/asgi.py` — `ProtocolTypeRouter`: HTTP → Django, WebSocket → `orders/routing.py` (`/ws/call/`). Server must run under Daphne (ASGI), not `runserver`.
- `orders/views.py` — Twilio webhooks: `twilio_voice_webhook` (returns the Stream TwiML; builds ws/wss URL from the request host) and `twilio_sms_status`. Both `@csrf_exempt`. Real paths are `/twilio/voice/` and `/twilio/sms-status/` (mounted under `twilio/` in `config/urls.py`). Unchanged by the Voice Agent migration.
- `orders/consumers.py` — `CallConsumer`, a thin relay: Twilio media (base64 mulaw) → `send_media` to the agent socket; agent messages → Twilio media events / function handling / hangup. See "Key mechanisms" below.
- `orders/agent.py` — builds the Voice Agent config: `build_agent_settings` (audio, models, prompt, keyterms, functions, greeting), `build_functions` (`place_order`, `end_conversation`), `load_keyterms`, `build_system_prompt` (reads `_dg_va_prompt.txt` if present, else embedded `VA_SYSTEM_PROMPT`), `get_menu_text` (menu from DB, "Pronunciations:" lines), `save_order_from_agent` (dict-based).
- `orders/notify.py` — `get_twilio_client`, `send_order_sms` (formatted SMS; on failure logs content and leaves `sms_sent=False` for retry).

### Key mechanisms (consumer)

- **Audio relay**: Twilio sends 160-byte 20ms mulaw chunks as base64 JSON; consumer decodes and calls `send_media`. Agent audio arrives as raw bytes; consumer re-encodes and sends `media` events with `streamSid`. Audio before `SettingsApplied` is dropped (Deepgram drops it server-side anyway); agent audio before Twilio's `start` event is buffered (~6s) and flushed when the stream begins.
- **Function calls**: the LLM calls `place_order` (save order + SMS via `sync_to_async(thread_sensitive=False)`) and `end_conversation`. Results go back via `send_function_call_response`. `end_conversation` (or a closed agent socket — the server-side path) schedules the Twilio REST hangup after a 3s delay (`HANGUP_DELAY`) so the goodbye audio finishes.
- **Barge-in**: Deepgram sends `UserStartedSpeaking`; the consumer forwards a Twilio `clear` event to flush the playback buffer. No echo filtering, no energy heuristics — the Voice Agent handles turn-taking natively.
- **System prompt**: source of truth is `_dg_va_prompt.txt` (repo root, git-tracked — the user-tested working copy). `build_system_prompt` injects the live menu from the DB (replacing the snapshot between `## The Menu` and `## Understanding Protein Options & Pricing` markers) and appends `FUNCTION_CALL_INSTRUCTIONS` (place_order → end_conversation sequence). If the file is missing, the embedded `VA_SYSTEM_PROMPT` template (same content, `{menu_text}` placeholder) is used — keep the two in sync when editing the prompt.
- **Keyterms**: `_dg_keyterms.txt` (repo root, git-tracked) holds 73 curated phonetic variants ("cow soy" → Khao Soi). `load_keyterms` reads it; passed to the listen provider `keyterms` field. Only works on nova-3 STT models — **do not switch to flux-general-en** (no keyterm support) unless recognition stops mattering.
- **Threading**: ORM + Twilio REST work runs through `sync_to_async(..., thread_sensitive=False)` — order save + SMS and the hangup call.
- **Hangup**: after `end_conversation` (or socket close), waits 3s, calls Twilio REST `status=completed`, closes the WebSocket.

## Menu data & conventions

- `orders/management/commands/seed_menu.py` holds the canonical `SAMPLE_MENU` (65 items). The command upserts by name and deletes items no longer listed. `chiang_mai_menu.xlsx` is the original data source.
- `MenuItem.modifiers` is a JSON list with a **format contract** that `get_menu_text` (agent.py) parses into prompt sections:
  - `'N - label'` (e.g. `'0 - no spice'`) → "Spice level:" line
  - starts with `'add '` (e.g. `'add chicken (+$3.09)'`) → "Add-ons (extra charge):" — paid additions
  - anything else (e.g. `'chicken'`, `'broccoli'`, `'pork (+$3.09)'`) → "Choice of:" — options; free unless the option carries a price
  - An option with `'(+$X)'` that does NOT start with `'add '` (e.g. `'pork (+$3.09)'` for Poh Piah, `'no iced (+$1.00)'` for Thai Iced Tea) is a **paid alternative** — it renders inside "Choice of:" so the AI presents it as an option, and picking it costs the extra amount.
  - Keep this format when editing menu items; the AI's pricing rules in the system prompt depend on it (free choices vs paid alternatives vs paid add-ons).
- `aliases` hold phonetic variants ("kalsoy" → Khao Soi). They feed the prompt's "Pronunciations:" lines (and the STT keyterm list via `_dg_keyterms.txt`). Adding aliases like `garlic moo` for Gra Dook Moo fixes Thai-English phrase recognition.

## Configuration

- `.env` (gitignored) is loaded via `python-dotenv` in `config/settings.py`. Copy `.env.example`. Keys: `DEEPGRAM_API_KEY`, `DEEPGRAM_VOICE_AGENT_STT_MODEL` (default `nova-3-general` — must stay nova-3 for keyterms), `DEEPGRAM_VOICE_AGENT_LLM_MODEL` (default `gpt-4o-mini`), `DEEPGRAM_VOICE_AGENT_TTS_MODEL` (default `aura-asteria-en`), `DEEPGRAM_VOICE_AGENT_TEMPERATURE` (default `0` — keep deterministic), `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `RESTAURANT_PHONE`, `RESTAURANT_NAME`.
- DB defaults to PostgreSQL via env vars (`DB_NAME`, `DB_USER`, ...); channel layer is in-memory (dev only).
- Logging: console INFO; `orders` and `daphne` loggers. Emoji-prefixed log lines (`🎙`) mark audio streaming; `USER:`/`ASSISTANT:` lines are conversation transcripts; `Function call:` lines show order saving.
- Deployment: `render.yaml` blueprint — Daphne start command, `migrate` pre-deploy. Note: `_dg_va_prompt.txt` / `_dg_keyterms.txt` are git-tracked and ship with the repo, so `build_system_prompt` always uses the file (with the live DB menu injected) in production too — the embedded `VA_SYSTEM_PROMPT` is only a fallback if the file is absent.

## Testing locally with a real call

1. `/start-testing-env` (daphne + ngrok + log tail)
2. Point the Twilio number's voice webhook at `https://<ngrok-url>/twilio/voice/`
3. Call the number; watch the log monitor for `USER:`/`ASSISTANT:` transcripts, function calls, and SMS send
