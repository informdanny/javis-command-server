from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID, uuid4

import websockets
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from websockets.exceptions import ConnectionClosed

from app.auth import require_agent_key, validate_agent_key_value
from app.config import get_settings
from app.handlers import build_status_reply
from app.providers import (
    build_interoperable_tools,
    build_provider_catalog,
    build_realtime_headers,
    build_realtime_upstream_url,
    build_session_update_event,
    resolve_voice_provider,
)
from app.realtime_tools import build_function_output_event, execute_realtime_tool_call, extract_realtime_tool_calls
from app.router import route_command
from app.schemas import (
    BackgroundTranscriptionResponse,
    CommandAction,
    CommandRequest,
    CommandResponse,
    Intent,
    Status,
    VoiceProvider,
    VoiceProvidersResponse,
    VoiceSessionConfigRequest,
    VoiceSessionConfigResponse,
)
from app.transcription import transcribe_bytes_with_xai, transcribe_with_xai
from app.voice_memory import (
    VoiceMemoryState,
    build_memory_aware_instructions,
    create_voice_memory,
    remember_realtime_event,
    reset_if_stale,
)

APP_VERSION = "0.2.0"


logger = logging.getLogger("javis.command.server")


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(message)s")


def _log_event(event: str, **fields: object) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str))


def _ensure_runtime_state(app: FastAPI) -> None:
    if not hasattr(app.state, "start_time"):
        app.state.start_time = time.monotonic()
    if not hasattr(app.state, "seen_events"):
        app.state.seen_events = {}
    if not hasattr(app.state, "seen_lock"):
        app.state.seen_lock = threading.Lock()
    if not hasattr(app.state, "mode_lock"):
        app.state.mode_lock = threading.Lock()
    if not hasattr(app.state, "desired_mode"):
        app.state.desired_mode = "armed"
    if not hasattr(app.state, "voice_memory_lock"):
        app.state.voice_memory_lock = threading.Lock()
    if not hasattr(app.state, "voice_memories"):
        app.state.voice_memories = {}


def _get_desired_mode(app: FastAPI) -> str:
    _ensure_runtime_state(app)
    with app.state.mode_lock:
        return str(app.state.desired_mode)


def _set_desired_mode(app: FastAPI, mode: str) -> None:
    _ensure_runtime_state(app)
    with app.state.mode_lock:
        app.state.desired_mode = mode


def _is_duplicate_event(app: FastAPI, event_id: UUID) -> bool:
    settings = get_settings()
    now = time.monotonic()
    _ensure_runtime_state(app)
    with app.state.seen_lock:
        stale_before = now - settings.duplicate_ttl_seconds
        stale_ids = [evt for evt, seen_at in app.state.seen_events.items() if seen_at < stale_before]
        for evt in stale_ids:
            del app.state.seen_events[evt]

        if event_id in app.state.seen_events:
            return True

        app.state.seen_events[event_id] = now
        return False


def _normalize_device_id(raw_device_id: str | None) -> str:
    text = (raw_device_id or "").strip()
    if not text:
        return "default"
    normalized = re.sub(r"[^a-zA-Z0-9_.-]", "-", text)
    normalized = normalized[:64].strip("-")
    return normalized or "default"


def _memory_key(provider: VoiceProvider, device_id: str) -> str:
    return f"{provider.value}:{device_id}"


def _get_or_create_voice_memory(app: FastAPI, key: str) -> VoiceMemoryState:
    _ensure_runtime_state(app)
    settings = get_settings()
    with app.state.voice_memory_lock:
        memory = app.state.voice_memories.get(key)
        if memory is None:
            memory = create_voice_memory(settings.voice_memory_max_events)
            app.state.voice_memories[key] = memory
        reset_if_stale(memory, settings.voice_memory_ttl_seconds)
        return memory


def _build_voice_instructions(app: FastAPI, key: str) -> str:
    settings = get_settings()
    memory = _get_or_create_voice_memory(app, key)
    with app.state.voice_memory_lock:
        return build_memory_aware_instructions(settings.voice_system_prompt, memory)


def _remember_voice_event(app: FastAPI, key: str, event: dict[str, object]) -> None:
    _ensure_runtime_state(app)
    memory = _get_or_create_voice_memory(app, key)
    with app.state.voice_memory_lock:
        prior_name = memory.preferred_name
        remember_realtime_event(memory, event)
        if memory.preferred_name and memory.preferred_name != prior_name:
            _log_event("voice_memory_name_set", memory_key=key, preferred_name=memory.preferred_name)


_configure_logging()
app = FastAPI(title="Javis Command Server", version=APP_VERSION)


@app.on_event("startup")
def startup_event() -> None:
    _ensure_runtime_state(app)
    settings = get_settings()
    _log_event("startup", service=settings.service_name, version=APP_VERSION, duplicate_ttl=settings.duplicate_ttl_seconds)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = uuid4()
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = str(request_id)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", uuid4())
    _log_event("unhandled_exception", request_id=request_id, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal server error", "request_id": str(request_id)})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.service_name, "version": APP_VERSION}


@app.post("/v1/commands", response_model=CommandResponse)
def commands(payload: CommandRequest, request: Request, _: None = Depends(require_agent_key)) -> CommandResponse:
    settings = get_settings()
    _ensure_runtime_state(app)
    request_id = request.state.request_id

    _log_event(
        "command_received",
        request_id=request_id,
        event_id=payload.event_id,
        device_id=payload.device_id,
        source=payload.source.value,
        trigger=payload.trigger.value,
        command_text=payload.command_text,
    )

    if _is_duplicate_event(app, payload.event_id):
        reply = CommandResponse(
            request_id=request_id,
            status=Status.ignored,
            intent=Intent.unknown,
            reply_text="duplicate event ignored",
            speak=False,
            action=CommandAction(type="none"),
            server_ts=datetime.now(UTC),
        )
        _log_event("command_duplicate", request_id=request_id, event_id=payload.event_id)
        return reply

    route = route_command(payload.command_text)
    reply_text = route.reply_text

    if route.intent == Intent.status:
        reply_text = build_status_reply(
            start_time_monotonic=app.state.start_time,
            service_name=settings.service_name,
            version=APP_VERSION,
            desired_mode=_get_desired_mode(app),
        )
    elif route.intent == Intent.set_mode and route.action_value:
        _set_desired_mode(app, route.action_value)

    response = CommandResponse(
        request_id=request_id,
        status=route.status,
        intent=route.intent,
        reply_text=reply_text,
        speak=route.speak,
        action=CommandAction(type=route.action_type, value=route.action_value),
        server_ts=datetime.now(UTC),
    )

    _log_event(
        "command_response",
        request_id=request_id,
        status=response.status.value,
        intent=response.intent.value,
        action_type=response.action.type,
        action_value=response.action.value,
    )
    return response


@app.get("/v1/voice/providers", response_model=VoiceProvidersResponse)
def voice_providers(_: None = Depends(require_agent_key)) -> VoiceProvidersResponse:
    settings = get_settings()
    default_provider = resolve_voice_provider(settings, None)
    return VoiceProvidersResponse(default_provider=default_provider, providers=build_provider_catalog(settings))


@app.post("/v1/voice/session-config", response_model=VoiceSessionConfigResponse)
def voice_session_config(
    payload: VoiceSessionConfigRequest,
    _: None = Depends(require_agent_key),
) -> VoiceSessionConfigResponse:
    settings = get_settings()
    provider = resolve_voice_provider(settings, payload.provider)
    return VoiceSessionConfigResponse(
        provider=provider,
        websocket_path=f"/v1/voice/realtime?provider={provider.value}",
        upstream_url=build_realtime_upstream_url(settings, provider),
        session_update=build_session_update_event(
            settings,
            provider,
            instructions=payload.instructions,
            voice=payload.voice,
        ),
        tools=build_interoperable_tools(),
    )


@app.post("/v1/background/transcriptions", response_model=BackgroundTranscriptionResponse)
async def background_transcriptions(
    file: UploadFile = File(...),
    provider: VoiceProvider = Form(default=VoiceProvider.xai),
    language: str | None = Form(default=None),
    diarize: bool = Form(default=True),
    multichannel: bool = Form(default=False),
    channels: int | None = Form(default=None),
    audio_format: str | None = Form(default=None),
    sample_rate: int | None = Form(default=None),
    apply_formatting: bool = Form(default=True),
    _: None = Depends(require_agent_key),
) -> BackgroundTranscriptionResponse:
    if provider != VoiceProvider.xai:
        raise HTTPException(status_code=400, detail="background transcription currently supports only xai")

    settings = get_settings()
    payload = await transcribe_with_xai(
        settings=settings,
        upload=file,
        language=language,
        diarize=diarize,
        multichannel=multichannel,
        channels=channels,
        audio_format=audio_format,
        sample_rate=sample_rate,
        apply_formatting=apply_formatting,
    )
    return BackgroundTranscriptionResponse(
        provider=provider,
        text=str(payload.get("text") or ""),
        duration=payload.get("duration"),
        language=payload.get("language"),
        diarized=diarize,
        words=list(payload.get("words") or []),
        channels=list(payload.get("channels") or []),
    )


@app.post("/v1/background/transcriptions/raw", response_model=BackgroundTranscriptionResponse)
async def background_transcriptions_raw(
    request: Request,
    provider: VoiceProvider = VoiceProvider.xai,
    filename: str | None = None,
    language: str | None = None,
    diarize: bool = True,
    multichannel: bool = False,
    channels: int | None = None,
    audio_format: str | None = None,
    sample_rate: int | None = None,
    apply_formatting: bool = True,
    _: None = Depends(require_agent_key),
) -> BackgroundTranscriptionResponse:
    if provider != VoiceProvider.xai:
        raise HTTPException(status_code=400, detail="background transcription currently supports only xai")

    file_bytes = await request.body()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="raw audio body is required")

    settings = get_settings()
    payload = await transcribe_bytes_with_xai(
        settings=settings,
        filename=filename or "segment.wav",
        file_bytes=file_bytes,
        content_type=request.headers.get("content-type") or "application/octet-stream",
        language=language,
        diarize=diarize,
        multichannel=multichannel,
        channels=channels,
        audio_format=audio_format,
        sample_rate=sample_rate,
        apply_formatting=apply_formatting,
    )
    return BackgroundTranscriptionResponse(
        provider=provider,
        text=str(payload.get("text") or ""),
        duration=payload.get("duration"),
        language=payload.get("language"),
        diarized=diarize,
        words=list(payload.get("words") or []),
        channels=list(payload.get("channels") or []),
    )


async def _proxy_client_to_upstream(
    websocket: WebSocket,
    upstream,
    provider: VoiceProvider,
    *,
    memory_key: str,
) -> None:
    settings = get_settings()
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        text = message.get("text")
        if text is not None:
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                await upstream.send(text)
                continue

            if isinstance(event, dict) and event.get("type") == "session.update":
                instructions = _build_voice_instructions(app, memory_key)
                event = build_session_update_event(settings, provider, existing_event=event, instructions=instructions)
                await upstream.send(json.dumps(event))
            else:
                await upstream.send(text)
            continue

        data = message.get("bytes")
        if data is not None:
            await upstream.send(data)


async def _flush_pending_tool_calls(
    upstream,
    pending_tool_calls: dict[str, object],
    *,
    provider: VoiceProvider,
    request_id: UUID,
) -> None:
    if not pending_tool_calls:
        return

    settings = get_settings()
    desired_mode = _get_desired_mode(app)

    for tool_call in pending_tool_calls.values():
        result = execute_realtime_tool_call(
            tool_call,
            service_name=settings.service_name,
            version=APP_VERSION,
            start_time_monotonic=app.state.start_time,
            desired_mode=desired_mode,
        )
        if result.requested_mode:
            _set_desired_mode(app, result.requested_mode)
            desired_mode = result.requested_mode
        _log_event(
            "voice_tool_call",
            request_id=request_id,
            provider=provider.value,
            tool_name=result.name,
            call_id=result.call_id,
            ok=result.output.get("ok"),
        )
        await upstream.send(json.dumps(build_function_output_event(result)))

    pending_tool_calls.clear()
    await upstream.send(json.dumps({"type": "response.create"}))


async def _proxy_upstream_to_client(
    websocket: WebSocket,
    upstream,
    *,
    provider: VoiceProvider,
    request_id: UUID,
    memory_key: str,
    connected_at_monotonic: float,
) -> None:
    pending_tool_calls: dict[str, object] = {}
    first_audio_delta_logged = False
    async for message in upstream:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            flush_after_forward = False
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                event = None

            if isinstance(event, dict):
                _remember_voice_event(app, memory_key, event)
                for tool_call in extract_realtime_tool_calls(event):
                    pending_tool_calls.setdefault(tool_call.call_id, tool_call)
                flush_after_forward = event.get("type") == "response.done" and bool(pending_tool_calls)
                if not first_audio_delta_logged and event.get("type") in {"response.audio.delta", "response.output_audio.delta"}:
                    first_audio_delta_logged = True
                    latency_ms = int((time.monotonic() - connected_at_monotonic) * 1000)
                    _log_event(
                        "voice_first_audio_delta",
                        request_id=request_id,
                        provider=provider.value,
                        memory_key=memory_key,
                        ms_since_connect=latency_ms,
                    )

            await websocket.send_text(message)

            if flush_after_forward:
                await _flush_pending_tool_calls(
                    upstream,
                    pending_tool_calls,
                    provider=provider,
                    request_id=request_id,
                )


@app.websocket("/v1/voice/realtime")
async def voice_realtime_proxy(websocket: WebSocket) -> None:
    settings = get_settings()
    provider_raw = websocket.query_params.get("provider")
    device_id = _normalize_device_id(websocket.query_params.get("device_id"))
    try:
        provider = resolve_voice_provider(settings, VoiceProvider(provider_raw) if provider_raw else None)
        validate_agent_key_value(settings, websocket.headers.get("x-agent-key"))
        upstream_url = build_realtime_upstream_url(settings, provider)
        upstream_headers = build_realtime_headers(settings, provider)
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    request_id = uuid4()
    memory_key = _memory_key(provider, device_id)
    _log_event(
        "voice_realtime_connect",
        request_id=request_id,
        provider=provider.value,
        upstream_url=upstream_url,
        device_id=device_id,
        memory_key=memory_key,
    )

    try:
        async with websockets.connect(
            upstream_url,
            additional_headers=upstream_headers,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
        ) as upstream:
            connection_started_at = time.monotonic()
            instructions = _build_voice_instructions(app, memory_key)
            await upstream.send(json.dumps(build_session_update_event(settings, provider, instructions=instructions)))

            client_task = asyncio.create_task(
                _proxy_client_to_upstream(websocket, upstream, provider, memory_key=memory_key)
            )
            upstream_task = asyncio.create_task(
                _proxy_upstream_to_client(
                    websocket,
                    upstream,
                    provider=provider,
                    request_id=request_id,
                    memory_key=memory_key,
                    connected_at_monotonic=connection_started_at,
                )
            )
            done, pending = await asyncio.wait({client_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
    except ConnectionClosed as exc:
        _log_event("voice_realtime_upstream_closed", request_id=request_id, provider=provider.value, code=exc.code)
    except WebSocketDisconnect:
        _log_event("voice_realtime_client_closed", request_id=request_id, provider=provider.value)
    except Exception as exc:
        _log_event("voice_realtime_error", request_id=request_id, provider=provider.value, error=str(exc))
        with suppress(RuntimeError):
            await websocket.send_text(json.dumps({"type": "error", "error": {"message": str(exc)}}))
    finally:
        with suppress(RuntimeError):
            await websocket.close()
