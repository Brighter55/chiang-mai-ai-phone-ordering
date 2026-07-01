# start-testing-env

Start the AI phone ordering test environment — three concurrent shells for
Daphne (ASGI server), ngrok (public tunnel), and live log monitoring.

## Usage

```
/start-testing-env
```

Or from the terminal:
```
! /start-testing-env
```

## What it does

Launches three background processes to test Twilio phone calls locally:

| # | Process | Port | Purpose |
|---|---------|------|---------|
| 1 | Daphne   | 8000 | Django Channels ASGI server (HTTP + WebSocket) |
| 2 | ngrok    | —    | Public HTTPS tunnel → localhost:8000 |
| 3 | Monitor  | —    | Tails Daphne logs for call activity |

## Implementation

### Shell 1 — Daphne Server

```powershell
cd C:\Users\meanp\Desktop\VSCODE\chiang-mai-ai
.\venv\Scripts\daphne -p 8000 -b 0.0.0.0 config.asgi:application
```

Serves both HTTP (Twilio webhooks at `/voice/`, `/sms/`) and WebSocket
(Twilio Media Streams at `/ws/call/`). Output goes to a background task file.

### Shell 2 — ngrok Tunnel

```powershell
ngrok http 8000 --log=stdout
```

Exposes the local server at a public URL like
`https://<random>.ngrok-free.dev`. Update your Twilio phone number's webhook
to point at:

```
https://<ngrok-url>.ngrok-free.dev/voice/
```

The ngrok web inspector is available at `http://127.0.0.1:4040`.

### Shell 3 — Log Monitor

```powershell
Get-Content <daphne-output-file> -Wait -Tail 10
```

Tail the Daphne server's background task output file to see incoming calls,
STT transcripts, AI responses, and TTS timing in real time.

## Twilio Webhook URLs

| Purpose | URL |
|---------|-----|
| Voice (inbound call) | `https://<ngrok-url>.ngrok-free.dev/voice/` |
| SMS status callback | `https://<ngrok-url>.ngrok-free.dev/sms/` |

## Call Flow

1. Customer dials Twilio number → Twilio POSTs to `/voice/`
2. `twilio_voice_webhook` returns TwiML with `<Stream>` connecting to WebSocket
3. `CallConsumer` accepts WebSocket → starts Deepgram STT → plays greeting
4. Audio flows: **Twilio → Deepgram STT → OpenAI → Deepgram TTS → Twilio**
5. When order is complete → saved to DB → SMS sent to restaurant phone

## Related

- [AI Phone Ordering Project](/CLAUDE.md)
- Twilio Console: https://console.twilio.com
- ngrok Dashboard: http://127.0.0.1:4040
