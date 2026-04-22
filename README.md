# Javis Server (Local + Render)

This folder is the backend for three current lanes:

- Command routing for the existing ESP32/desktop simulator flow
- Provider-neutral realtime session bootstrap for OpenAI and xAI
- xAI background speech-to-text ingestion for the always-on transcript lane

Full API reference lives in `/Users/danieldvalentine/My Agent/Docs/SERVER_API_REFERENCE.md`.

FastAPI live docs are available at `http://127.0.0.1:8000/docs` when the server is running locally.

## Setup

```bash
cd "/Users/danieldvalentine/My Agent/Server"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Set at least:

- `AGENT_API_KEY`
- `XAI_API_KEY` for background transcription and xAI realtime A/B
- `OPENAI_API_KEY` for OpenAI realtime A/B

Optional tuning:

- `VOICE_MEMORY_TTL_SECONDS` (default `1800`)
- `VOICE_MEMORY_MAX_EVENTS` (default `12`)
- `WEB_SEARCH_TIMEOUT_SECONDS` (default `8.0`)
- `WEB_SEARCH_MAX_RESULTS` (default `3`)

## Run Locally

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Current Endpoints

- `GET /healthz`
- `POST /v1/commands`
- `GET /v1/voice/providers`
- `POST /v1/voice/session-config`
- `WS /v1/voice/realtime`
- `POST /v1/background/transcriptions`
- `POST /v1/background/transcriptions/raw`

Three shared realtime tools are injected into both providers today:

- `get_agent_status`
- `set_agent_mode`
- `search_web`

Important limitation:

- `set_agent_mode` updates the server-side `desired_mode` state and works for A/B tool-calling tests.
- It does not yet push that mode change down to the ESP32 firmware. Device transport is the next integration slice.
- `search_web` uses DuckDuckGo Instant Answer as a lightweight, no-extra-key web lane for realtime tool calls.

## Quick Tests

Run the existing command harness:

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
python tools/local_test_harness.py
```

List enabled realtime providers:

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
curl -sS http://127.0.0.1:8000/v1/voice/providers \
  -H "x-agent-key: $AGENT_API_KEY"
```

Fetch a provider-specific session bootstrap:

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
curl -sS http://127.0.0.1:8000/v1/voice/session-config \
  -H "content-type: application/json" \
  -H "x-agent-key: $AGENT_API_KEY" \
  --data '{"provider":"openai"}'
```

Upload an audio file to the xAI background transcription lane:

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
curl -sS http://127.0.0.1:8000/v1/background/transcriptions \
  -H "x-agent-key: $AGENT_API_KEY" \
  -F "provider=xai" \
  -F "diarize=true" \
  -F "file=@sample.wav;type=audio/wav"
```

If you omit `language`, the server currently defaults formatted xAI transcripts to `en` because xAI requires `language` when `format=true`.

Upload a raw WAV body the way the ESP32 firmware does:

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
curl -sS "http://127.0.0.1:8000/v1/background/transcriptions/raw?provider=xai&diarize=true&audio_format=wav&sample_rate=16000&filename=segment.wav" \
  -H "x-agent-key: $AGENT_API_KEY" \
  -H "content-type: audio/wav" \
  --data-binary @sample.wav
```

## Tests

```bash
cd "/Users/danieldvalentine/My Agent/Server"
source .venv/bin/activate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```

## Notes

- The server reads `.env` automatically through `pydantic-settings`.
- `tools/device_simulator.py` and `tools/local_test_harness.py` fall back to `.env` when `AGENT_API_KEY` is not already exported.
- The realtime WebSocket relay is server-to-server and is intended to sit behind the ESP32 client or a local bridge.
- The relay accepts an optional `device_id` query param on `WS /v1/voice/realtime` and uses it to scope short-term conversation memory.
- Conversation continuity is in-memory only (process-local): it survives wake/session reconnects but resets on server restart or TTL expiry.
- Background transcription currently supports only `xai` in the implemented API.
- `POST /v1/background/transcriptions/raw` exists specifically to keep the ESP32 upload path simple by accepting a raw audio body instead of multipart form data.
- When `apply_formatting=true` and no `language` is supplied, the server currently falls back to `en` for xAI STT compatibility.
