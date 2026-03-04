from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import Intent, Status


_SET_MODE_PATTERN = re.compile(r"^set\s+mode\s+(muted|armed)$", re.IGNORECASE)


@dataclass
class RouteResult:
    status: Status
    intent: Intent
    reply_text: str
    speak: bool
    action_type: str
    action_value: str | None = None


def route_command(command_text: str) -> RouteResult:
    normalized = " ".join(command_text.strip().lower().split())

    if normalized == "ping":
        return RouteResult(
            status=Status.ok,
            intent=Intent.ping,
            reply_text="pong",
            speak=True,
            action_type="none",
        )

    if normalized == "status":
        return RouteResult(
            status=Status.ok,
            intent=Intent.status,
            reply_text="status ready",
            speak=True,
            action_type="status",
        )

    mode_match = _SET_MODE_PATTERN.match(normalized)
    if mode_match:
        mode = mode_match.group(1)
        return RouteResult(
            status=Status.ok,
            intent=Intent.set_mode,
            reply_text=f"mode set to {mode}",
            speak=True,
            action_type="set_mode",
            action_value=mode,
        )

    return RouteResult(
        status=Status.ignored,
        intent=Intent.unknown,
        reply_text="supported commands: ping, status, set mode muted, set mode armed",
        speak=True,
        action_type="none",
    )
