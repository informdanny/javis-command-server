from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import require_agent_key
from app.config import get_settings
from app.handlers import build_status_reply
from app.router import route_command
from app.schemas import CommandAction, CommandRequest, CommandResponse, Intent, Status

APP_VERSION = "0.1.0"


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
        )

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
