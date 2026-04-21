import os
import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ["AGENT_API_KEY"] = "test-key"
os.environ["XAI_API_KEY"] = "xai-test-key"
os.environ["OPENAI_API_KEY"] = "openai-test-key"

from app.main import app  # noqa: E402
from app.config import get_settings  # noqa: E402


get_settings.cache_clear()
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_runtime_state():
    app.state.seen_events = {}
    app.state.seen_lock = threading.Lock()
    app.state.mode_lock = threading.Lock()
    app.state.desired_mode = "armed"
    yield


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


def test_voice_providers_ok():
    response = client.get("/v1/voice/providers", headers={"x-agent-key": "test-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["default_provider"] in {"xai", "openai"}
    providers = {item["provider"]: item for item in body["providers"]}
    assert providers["xai"]["enabled"] is True
    assert providers["openai"]["enabled"] is True


def test_voice_session_config_injects_tools():
    response = client.post(
        "/v1/voice/session-config",
        headers={"x-agent-key": "test-key"},
        json={"provider": "xai"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "xai"
    tool_names = {tool["name"] for tool in body["tools"]}
    assert "get_agent_status" in tool_names
    assert "set_agent_mode" in tool_names
    assert body["session_update"]["type"] == "session.update"


def test_background_transcription_requires_auth():
    response = client.post(
        "/v1/background/transcriptions",
        files={"file": ("sample.wav", b"RIFF", "audio/wav")},
    )
    assert response.status_code == 401


def test_background_transcription_xai_success(monkeypatch):
    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "text": "hello world",
                "duration": 1.23,
                "language": "en",
                "words": [{"word": "hello", "start": 0.0, "end": 0.5, "speaker": 0}],
                "channels": [],
            }

    async def fake_post(self, url, headers=None, data=None, files=None):
        assert url == "https://api.x.ai/v1/stt"
        assert headers == {"Authorization": "Bearer xai-test-key"}
        assert data["diarize"] == "true"
        assert files["file"][0] == "sample.wav"
        return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    response = client.post(
        "/v1/background/transcriptions",
        headers={"x-agent-key": "test-key"},
        files={"file": ("sample.wav", b"RIFF", "audio/wav")},
        data={"provider": "xai", "diarize": "true", "language": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "xai"
    assert body["text"] == "hello world"
    assert body["diarized"] is True


def test_background_transcription_raw_xai_success(monkeypatch):
    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "text": "raw hello world",
                "duration": 2.5,
                "language": "en",
                "words": [],
                "channels": [],
            }

    async def fake_post(self, url, headers=None, data=None, files=None):
        assert url == "https://api.x.ai/v1/stt"
        assert headers == {"Authorization": "Bearer xai-test-key"}
        assert data["sample_rate"] == "16000"
        assert data["language"] == "en"
        assert files["file"][0] == "segment.wav"
        assert files["file"][2] == "audio/wav"
        return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    response = client.post(
        "/v1/background/transcriptions/raw?provider=xai&filename=segment.wav&sample_rate=16000",
        headers={"x-agent-key": "test-key", "content-type": "audio/wav"},
        content=b"RIFFrawwav",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "xai"
    assert body["text"] == "raw hello world"


def test_background_transcription_xai_defaults_language_when_formatting_enabled(monkeypatch):
    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "text": "hello world",
                "duration": 1.23,
                "language": "en",
                "words": [],
                "channels": [],
            }

    async def fake_post(self, url, headers=None, data=None, files=None):
        assert url == "https://api.x.ai/v1/stt"
        assert headers == {"Authorization": "Bearer xai-test-key"}
        assert data["format"] == "true"
        assert data["language"] == "en"
        assert files["file"][0] == "sample.wav"
        return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    response = client.post(
        "/v1/background/transcriptions",
        headers={"x-agent-key": "test-key"},
        files={"file": ("sample.wav", b"RIFF", "audio/wav")},
        data={"provider": "xai", "diarize": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "xai"
    assert body["text"] == "hello world"


def test_background_transcription_raw_requires_body():
    response = client.post(
        "/v1/background/transcriptions/raw?provider=xai",
        headers={"x-agent-key": "test-key", "content-type": "audio/wav"},
        content=b"",
    )
    assert response.status_code == 400


def test_status_reports_server_desired_mode():
    headers = {"x-agent-key": "test-key"}
    set_mode = client.post("/v1/commands", headers=headers, json=_payload("set mode muted"))
    assert set_mode.status_code == 200

    status_response = client.post("/v1/commands", headers=headers, json=_payload("status"))

    assert status_response.status_code == 200
    assert "desired_mode=muted" in status_response.json()["reply_text"]
