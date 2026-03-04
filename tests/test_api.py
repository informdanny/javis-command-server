import os
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ["AGENT_API_KEY"] = "test-key"

from app.main import app  # noqa: E402


client = TestClient(app)


def _payload(command_text: str, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "device_id": "esp32-lab-1",
        "source": "bridge",
        "trigger": "direct_test",
        "command_text": command_text,
        "ts_ms": 123456789,
        "meta": {"test": True},
    }


def test_healthz_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_requires_auth_header():
    response = client.post("/v1/commands", json=_payload("ping"))
    assert response.status_code == 401


def test_invalid_auth_header():
    response = client.post("/v1/commands", headers={"x-agent-key": "wrong"}, json=_payload("ping"))
    assert response.status_code == 401


def test_ping_command_success():
    response = client.post("/v1/commands", headers={"x-agent-key": "test-key"}, json=_payload("ping"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["intent"] == "ping"
    assert body["reply_text"] == "pong"


def test_duplicate_event_ignored():
    dup_id = str(uuid4())
    headers = {"x-agent-key": "test-key"}
    first = client.post("/v1/commands", headers=headers, json=_payload("ping", event_id=dup_id))
    second = client.post("/v1/commands", headers=headers, json=_payload("ping", event_id=dup_id))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "ignored"


def test_validation_error_for_bad_source():
    payload = _payload("ping")
    payload["source"] = "invalid-source"
    response = client.post("/v1/commands", headers={"x-agent-key": "test-key"}, json=payload)
    assert response.status_code == 422
