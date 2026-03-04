from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Source(str, Enum):
    esp32 = "esp32"
    bridge = "bridge"


class Trigger(str, Enum):
    wakeword = "wakeword"
    manual_boot = "manual_boot"
    vad_speech = "vad_speech"
    direct_test = "direct_test"


class Status(str, Enum):
    ok = "ok"
    ignored = "ignored"
    error = "error"


class Intent(str, Enum):
    ping = "ping"
    status = "status"
    set_mode = "set_mode"
    unknown = "unknown"


class CommandRequest(BaseModel):
    event_id: UUID
    device_id: str = Field(min_length=1, max_length=64)
    source: Source
    trigger: Trigger
    command_text: str = Field(min_length=1, max_length=160)
    ts_ms: int = Field(ge=0)
    wake_channel: int | None = None
    loudness: float | None = Field(default=None, ge=0.0, le=1.0)
    meta: dict[str, Any] | None = None


class CommandAction(BaseModel):
    type: str
    value: str | None = None


class CommandResponse(BaseModel):
    request_id: UUID
    status: Status
    intent: Intent
    reply_text: str
    speak: bool
    action: CommandAction
    server_ts: datetime
