# Javis Command Server

Minimal FastAPI server that validates and routes wake-triggered commands.

## Endpoints

- `GET /healthz`
- `POST /v1/commands` (requires `x-agent-key` header)

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Local Test

```bash
pytest -q
```

## Send Test Command

```bash
python tools/send_test_command.py --url http://127.0.0.1:8000 --api-key dev-local-key --command ping
```
