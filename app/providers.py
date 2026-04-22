from __future__ import annotations

from urllib.parse import urlencode

from fastapi import HTTPException, status

from app.config import Settings
from app.schemas import VoiceProvider, VoiceProviderInfo


def build_interoperable_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "get_agent_status",
            "description": "Get the current status of the Jarvis device and service.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "set_agent_mode",
            "description": "Change the Jarvis device mode between armed and muted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["armed", "muted"],
                        "description": "The desired device mode.",
                    }
                },
                "required": ["mode"],
                "additionalProperties": False,
            },
        },
    ]


def _merge_tools(existing_tools: list[dict] | None) -> list[dict]:
    merged: dict[str, dict] = {}
    for tool in existing_tools or []:
        name = tool.get("name")
        if name:
            merged[name] = tool
    for tool in build_interoperable_tools():
        merged[tool["name"]] = tool
    return list(merged.values())


def _default_provider(settings: Settings) -> VoiceProvider:
    try:
        return VoiceProvider(settings.default_voice_provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"invalid DEFAULT_VOICE_PROVIDER={settings.default_voice_provider!r}",
        ) from exc


def resolve_voice_provider(settings: Settings, provider: VoiceProvider | None) -> VoiceProvider:
    return provider or _default_provider(settings)


def build_provider_catalog(settings: Settings) -> list[VoiceProviderInfo]:
    return [
        VoiceProviderInfo(
            provider=VoiceProvider.xai,
            enabled=bool(settings.xai_api_key),
            websocket_path="/v1/voice/realtime?provider=xai",
            upstream_url=settings.xai_realtime_url,
            turn_detection="server_vad",
            notes=[
                "xAI realtime uses server_vad only.",
                "xAI background transcription is the default always-on lane.",
            ],
        ),
        VoiceProviderInfo(
            provider=VoiceProvider.openai,
            enabled=bool(settings.openai_api_key),
            websocket_path="/v1/voice/realtime?provider=openai",
            upstream_url=f"{settings.openai_realtime_url}?{urlencode({'model': settings.openai_realtime_model})}",
            model=settings.openai_realtime_model,
            turn_detection=settings.openai_turn_detection_type,
            notes=[
                "OpenAI defaults to semantic_vad in this server config for human-like turn taking.",
                "Use this lane for A/B testing against xAI realtime.",
            ],
        ),
    ]


def build_realtime_upstream_url(settings: Settings, provider: VoiceProvider) -> str:
    if provider == VoiceProvider.xai:
        return settings.xai_realtime_url
    return f"{settings.openai_realtime_url}?{urlencode({'model': settings.openai_realtime_model})}"


def build_realtime_headers(settings: Settings, provider: VoiceProvider) -> dict[str, str]:
    if provider == VoiceProvider.xai:
        if not settings.xai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="xai realtime is not configured",
            )
        return {"Authorization": f"Bearer {settings.xai_api_key}"}

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="openai realtime is not configured",
        )
    return {"Authorization": f"Bearer {settings.openai_api_key}"}


def build_session_update_event(
    settings: Settings,
    provider: VoiceProvider,
    *,
    instructions: str | None = None,
    voice: str | None = None,
    existing_event: dict | None = None,
) -> dict:
    event = existing_event.copy() if existing_event else {"type": "session.update", "session": {}}
    event["type"] = "session.update"
    session = dict(event.get("session") or {})

    caller_instructions = session.get("instructions")
    base_instructions = instructions or settings.voice_system_prompt
    if isinstance(caller_instructions, str) and caller_instructions.strip():
        if base_instructions.strip():
            session["instructions"] = (
                f"{base_instructions.strip()}\n\n"
                "Additional caller instructions:\n"
                f"{caller_instructions.strip()}"
            )
        else:
            session["instructions"] = caller_instructions.strip()
    elif base_instructions.strip():
        session["instructions"] = base_instructions.strip()
    session["tools"] = _merge_tools(session.get("tools"))

    if provider == VoiceProvider.xai:
        session.setdefault("voice", voice or settings.xai_voice)
        session.setdefault(
            "turn_detection",
            {
                "type": "server_vad",
                "threshold": settings.xai_vad_threshold,
                "silence_duration_ms": settings.xai_vad_silence_duration_ms,
                "prefix_padding_ms": settings.xai_vad_prefix_padding_ms,
            },
        )
        session.setdefault(
            "audio",
            {
                "input": {"format": {"type": "audio/pcm", "rate": settings.realtime_audio_sample_rate}},
                "output": {"format": {"type": "audio/pcm", "rate": settings.realtime_audio_sample_rate}},
            },
        )
    else:
        session.setdefault("type", "realtime")
        session.setdefault("voice", voice or settings.openai_voice)
        session.setdefault("output_modalities", ["audio", "text"])
        session.setdefault(
            "turn_detection",
            {
                "type": settings.openai_turn_detection_type,
                "eagerness": settings.openai_semantic_vad_eagerness,
                "create_response": True,
                "interrupt_response": True,
            },
        )

    event["session"] = session
    return event
