# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI phone ordering system for Chiang Mai Thai Restaurant (St. Louis). A Twilio number forwards to the restaurant; when no one picks up, an AI assistant takes the order conversationally and pushes it to the restaurant's **Clover POS** as an open "Take out" ticket, with a formatted SMS to the restaurant phone as a backup. The agent also answers brief practical questions (location, hours, pickup), and — when `TRANSFER_PHONE` is configured — can hand the caller to a human. Stack: Django 5 + Channels (ASGI/Daphne) + **Deepgram Voice Agent API** (managed STT + LLM + TTS in one WebSocket) + Twilio Voice/SMS + **Clover POS** (REST v3).

## Commands

All commands run from the repo root on Windows (PowerShell). Python lives in `venv\`.

```powershell
# Install dependencies
.\venv\Scripts\pip install -r requirements.txt

# Migrate
.\venv\Scripts\python manage.py migrate

# Menu setup — pick ONE source of truth (they are alternatives, don't mix):
#   (a) seed_menu — offline seed from the embedded SAMPLE_MENU (65 curated
#       items; upserts by name and DELETES any item not in SAMPLE_MENU, so do
#       not run it against a Clover-synced menu)
#   (b) sync_menu_from_clover — pull names/prices/modifiers from the Clover
#       catalog, PRESERVING curated aliases/thai_name (--dry-run, --seed-aliases,
#       --delete-missing)
.\venv\Scripts\python manage.py seed_menu
.\venv\Scripts\python manage.py sync_menu_from_clover

# Run the server — use `python -m daphne`, NOT the daphne.exe shim,
# which fails silently with exit code 1 on this machine
.\venv\Scripts\python -m daphne -p 8000 -b 0.0.0.0 config.asgi:application

# Tests (orders/tests.py — transfer-to-human: phone normalization, the loop
# guard, the cold-transfer TwiML builder, and conditional function/prompt config)
.\venv\Scripts\python manage.py test orders

# Manually re-push a local order to Clover after a failed push (retry / sandbox check)
.\venv\Scripts\python manage.py push_order_to_clover 42   # --force to re-push

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
    → agent calls `place_order` → save local Order → SMS backup → Clover push (best-effort)
    → call ends SERVER-SIDE after place_order: quiet-period hangup (3s of agent silence)
      with a 16s safety timer; `end_conversation` only when there is no order
    → or `transfer_call` → cold-transfer via Twilio REST <Dial> (AI sockets torn down)
```

### Key files

- `config/asgi.py` — `ProtocolTypeRouter`: HTTP → Django, WebSocket → `orders/routing.py` (`/ws/call/`). Server must run under Daphne (ASGI), not `runserver`.
- `orders/views.py` — Twilio webhooks, all `@csrf_exempt`: `twilio_voice_webhook` (returns the Stream TwiML; builds ws/wss URL from the request host and passes `call_sid`, `caller_phone`, and an absolute `transfer_result_url` as stream parameters), `twilio_transfer_result` (`<Dial action>` callback — plays an apology + hangup when the human leg no-answers/busies/fails), and `twilio_sms_status`. Real paths: `/twilio/voice/`, `/twilio/transfer-result/`, `/twilio/sms-status/` (mounted under `twilio/` in `config/urls.py`).
- `orders/consumers.py` — `CallConsumer`, a thin relay: Twilio media (base64 mulaw) → `send_media` to the agent socket; agent messages → Twilio media events / function handling / hangup. See "Key mechanisms" below.
- `orders/agent.py` — builds the Voice Agent config: `build_agent_settings` (audio, models, prompt, keyterms, functions, greeting), `build_functions` (`place_order`, `end_conversation`, plus `transfer_call` when enabled), `load_keyterms` (with the 500-token budget backstop), `build_system_prompt` (reads `_dg_va_prompt.txt` if present, else embedded `VA_SYSTEM_PROMPT`), `get_menu_text` (menu from DB, "Pronunciations:" lines), `save_order_from_agent` (dict-based).
- `orders/clover.py` — Clover REST v3 client: `CloverClient` (Bearer token; catalog reads, order-type lookup, `create_atomic_order`), `build_atomic_order_payload` (modifier resolution + line-item notes), `send_order_to_clover` (best-effort, never raises). Backs the `sync_menu_from_clover` and `push_order_to_clover` commands.
- `orders/transfer.py` — pure helpers for transfer-to-human: `normalize_phone`, `transfer_enabled` (loop guard), `build_transfer_twiml`, and the `TRANSFER_INSTRUCTIONS` / `TRANSFER_DECLINE_INSTRUCTIONS` prompt blocks.
- `orders/notify.py` — `get_twilio_client`, `send_order_sms` (formatted SMS; on failure logs content and leaves `sms_sent=False` for retry).
- `orders/models.py` — `MenuItem` now carries `clover_item_id` + `clover_modifiers`; `Order` carries `clover_order_id`, `clover_pushed`, `clover_error` (migration `0005`).

### Key mechanisms (consumer)

- **Audio relay**: Twilio sends 160-byte 20ms mulaw chunks as base64 JSON; consumer decodes and calls `send_media`. Agent audio arrives as raw bytes; consumer re-encodes and sends `media` events with `streamSid`. Audio before `SettingsApplied` is dropped (Deepgram drops it server-side anyway); agent audio before Twilio's `start` event is buffered (~6s / 300 chunks) and flushed when the stream begins.
- **Order placement** (`place_order`): runs in `sync_to_async(..., thread_sensitive=False)` — `save_order_from_agent` creates the local `Order`/`OrderItem` rows, then `send_order_sms` sends the Twilio SMS backup, then `send_order_to_clover` pushes an atomic "Take out" order (best-effort: a Clover outage never blocks the call — `clover_error` is recorded for a later `push_order_to_clover` retry). Special requests end up as Clover line-item `note` text so they print on the kitchen ticket.
- **Function calls**: the LLM calls `place_order`, `end_conversation`, and (when transfers are enabled) `transfer_call`. Results go back via `send_function_call_response`. `transfer_call` is never given a dial target by the model — the destination comes from `TRANSFER_PHONE` only (toll-fraud guard).
- **Hangup after an order**: the model is unreliable at calling `end_conversation`, so after a successful `place_order` the consumer ends the call server-side. Each finished agent utterance (`AgentAudioDone`) re-arms a quiet timer (`POST_ORDER_QUIET_DELAY` = 3s); new agent speech (`AgentStartedSpeaking`) cancels it so it can't fire mid-sentence. Once the goodbye audio goes quiet, the call hangs up via Twilio REST `status=completed`. `ORDER_PLACED_HANGUP_DELAY` (16s) is a safety net in case the agent keeps talking.
- **Hangup without an order**: `end_conversation` (or a closed agent socket, the server-side path) hangs up after a 3s delay (`HANGUP_DELAY`) so the goodbye audio finishes — but only when no post-order hangup is already scheduled. Twilio's `stop` event (caller hung up) also hangs up.
- **Transfer to human**: `transfer_call` sends a Twilio REST call update replacing the `<Connect><Stream>` TwiML with an announcement `<Say>` + `<Dial TRANSFER_PHONE>` (action = `/twilio/transfer-result/`). Before touching the call it neutralizes every server-side hangup path (quiet timer + 16s safety timer) and sets `_transferred`, so no REST `status=completed` ever runs and kills the bridged call — Twilio owns the call from there. The `<Dial action>` callback apologizes and hangs up if the human leg fails.
- **Barge-in**: Deepgram sends `UserStartedSpeaking`; the consumer forwards a Twilio `clear` event to flush the playback buffer. No echo filtering, no energy heuristics — the Voice Agent handles turn-taking natively.
- **System prompt**: source of truth is `_dg_va_prompt.txt` (repo root, git-tracked — the user-tested working copy). `build_system_prompt` injects the live menu from the DB (replacing the snapshot between `## The Menu` and `## Understanding Protein Options & Pricing` markers), then appends `FUNCTION_CALL_INSTRUCTIONS` (place_order → end_conversation sequence + the "special requests go in `notes`, not `modifiers`" rule) and finally the transfer block — `TRANSFER_INSTRUCTIONS` when transfers are enabled, `TRANSFER_DECLINE_INSTRUCTIONS` when disabled. The file also contains the FAQ "Restaurant Info — Quick Facts" section so the agent can answer location/hours/pickup questions. If the file is missing, the embedded `VA_SYSTEM_PROMPT` template (same content, `{menu_text}` placeholder) is used — keep the two in sync when editing the prompt.
- **Keyterms**: `_dg_keyterms.txt` (repo root, git-tracked) holds curated phonetic variants ("cow soy" → Khao Soi). `load_keyterms` reads it; passed to the listen provider `keyterms` field. Only works on nova-3 STT models — **do not switch to flux-general-en** (no keyterm support) unless recognition stops mattering. Deepgram hard-caps keyterms at 500 tokens; `MAX_KEYTERM_WORDS` (220) is a backstop that drops the longest terms first so a future "add more keyterms" can't silently break every call.
- **Threading**: ORM + Twilio REST + Clover work runs through `sync_to_async(..., thread_sensitive=False)` — order save + SMS + Clover push and the hangup call.
- **Hangup**: after the post-order quiet period (or `end_conversation` / socket close), calls Twilio REST `status=completed`, then closes the WebSocket. Never after a successful transfer.

## Menu data & conventions

- Two ways to populate the menu, both driven by management commands (see Commands). `seed_menu.py` holds the canonical embedded `SAMPLE_MENU` (65 items, the original data source). `sync_menu_from_clover.py` is the production path: Clover is the source of truth for names/prices/modifiers, and it **preserves** curated `aliases`/`thai_name` on existing items so STT keyterms and Thai-name matching stay intact (`--seed-aliases` copies them from `SAMPLE_MENU` for brand-new items only). Stale Clover-linked items are marked `unavailable` by default (`--delete-missing` hard-deletes). `chiang_mai_menu.xlsx` is the original spreadsheet source.
- `MenuItem.modifiers` is a JSON list with a **format contract** that `get_menu_text` (agent.py) parses into prompt sections:
  - `'N - label'` (e.g. `'0 - no spice'`) → "Spice level:" line
  - starts with `'add '` (e.g. `'add chicken (+$3.09)'`) → "Add-ons (extra charge):" — paid additions
  - anything else (e.g. `'chicken'`, `'broccoli'`, `'pork (+$3.09)'`) → "Choice of:" — options; free unless the option carries a price
  - An option with `'(+$X)'` that does NOT start with `'add '` (e.g. `'pork (+$3.09)'` for Poh Piah, `'no iced (+$1.00)'` for Thai Iced Tea) is a **paid alternative** — it renders inside "Choice of:" so the AI presents it as an option, and picking it costs the extra amount.
  - Keep this format when editing menu items; the AI's pricing rules in the system prompt depend on it (free choices vs paid alternatives vs paid add-ons). `MenuItem.clover_modifiers` is separate and richer (Clover groups with kind/min-max and modifier ids/prices in cents) — don't confuse the two.
- `aliases` hold phonetic variants ("kalsoy" → Khao Soi). They feed the prompt's "Pronunciations:" lines (and the STT keyterm list via `_dg_keyterms.txt`). Adding aliases like `garlic moo` for Gra Dook Moo fixes Thai-English phrase recognition.
- When an order is pushed to Clover, `build_atomic_order_payload` resolves the LLM's `modifiers` strings against each item's Clover modifier groups (spice / choice / add-on, including paid amounts). Anything that matches no real modifier — plus each item's `notes` (e.g. "no vegetables") — is attached to the Clover line item as its free-form `note`, so special instructions reach the kitchen ticket. Multi-quantity items expand to one line per unit (Clover atomic orders ignore quantity for fixed-price items).

## Configuration

- `.env` (gitignored) is loaded via `python-dotenv` in `config/settings.py`. Copy `.env.example`. Keys: `DEEPGRAM_API_KEY`, `DEEPGRAM_VOICE_AGENT_STT_MODEL` (default `nova-3-general` — must stay nova-3 for keyterms), `DEEPGRAM_VOICE_AGENT_LLM_MODEL` (default `gpt-4o-mini`), `DEEPGRAM_VOICE_AGENT_TTS_MODEL` (default `aura-asteria-en`), `DEEPGRAM_VOICE_AGENT_TEMPERATURE` (default `0` — keep deterministic), `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `RESTAURANT_PHONE`, `RESTAURANT_NAME`, `TRANSFER_PHONE` (empty = transfers disabled).
- **Transfer config**: `TRANSFER_PHONE` must be a DIRECT staff line in E.164 — never `RESTAURANT_PHONE` (its AT&T no-answer forwarding would bounce the transfer back into the AI) and never `TWILIO_PHONE_NUMBER`. `transfer_enabled()` enforces this loop guard; when disabled, the prompt gets the polite-decline block and `transfer_call` is not exposed.
- **Clover config**: `CLOVER_MERCHANT_ID`, `CLOVER_API_TOKEN` (long-lived merchant token — API Access → Generate Token, not OAuth), `CLOVER_BASE_URL` (`https://api.clover.com` prod / `https://apisandbox.dev.clover.com` sandbox), `CLOVER_ORDER_TYPE_NAME` (default `Take out`), optional `CLOVER_ORDER_TYPE_ID` to bypass the `/order_types` lookup that some API tokens can't read (401). Adds the `requests` dependency.
- DB defaults to PostgreSQL via env vars (`DB_NAME`, `DB_USER`, ...); channel layer is in-memory (dev only).
- Logging: console INFO; `orders` and `daphne` loggers. Emoji-prefixed log lines (`🎙`) mark audio streaming; `USER:`/`ASSISTANT:` lines are conversation transcripts; `Function call:` lines show order saving / transfers (`📞`).
- Deployment: `render.yaml` blueprint — Daphne start command, `migrate` pre-deploy, plus `TRANSFER_PHONE` and `CLOVER_*` env vars. Note: `_dg_va_prompt.txt` / `_dg_keyterms.txt` are git-tracked and ship with the repo, so `build_system_prompt` always uses the file (with the live DB menu injected) in production too — the embedded `VA_SYSTEM_PROMPT` is only a fallback if the file is absent.

## Testing locally with a real call

1. `/start-testing-env` (daphne + ngrok + log tail)
2. Point the Twilio number's voice webhook at `https://<ngrok-url>/twilio/voice/`
3. Call the number; watch the log monitor for `USER:`/`ASSISTANT:` transcripts, function calls, and the Clover/SMS push
