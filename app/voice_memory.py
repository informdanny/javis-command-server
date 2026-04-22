from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


_CALL_ME_PATTERN = re.compile(r"\bcall me\s+([a-zA-Z][a-zA-Z0-9' -]{0,31})", re.IGNORECASE)
_MY_NAME_PATTERN = re.compile(r"\bmy name is\s+([a-zA-Z][a-zA-Z0-9' -]{0,31})", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass
class VoiceMemoryState:
    preferred_name: str | None = None
    recent_events: deque[tuple[str, str]] = field(default_factory=deque)
    updated_at_monotonic: float = field(default_factory=time.monotonic)


def create_voice_memory(max_events: int) -> VoiceMemoryState:
    clamped = max(4, min(32, int(max_events)))
    return VoiceMemoryState(recent_events=deque(maxlen=clamped))


def reset_if_stale(memory: VoiceMemoryState, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    now = time.monotonic()
    if (now - memory.updated_at_monotonic) <= ttl_seconds:
        return
    maxlen = memory.recent_events.maxlen or 12
    memory.preferred_name = None
    memory.recent_events = deque(maxlen=maxlen)
    memory.updated_at_monotonic = now


def remember_realtime_event(memory: VoiceMemoryState, event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return

    transcript: str | None = None
    role: str | None = None

    if event_type == "conversation.item.input_audio_transcription.completed":
        transcript = event.get("transcript")
        role = "user"
    elif event_type in {"response.audio_transcript.done", "response.output_audio_transcript.done"}:
        transcript = event.get("transcript")
        role = "assistant"
    elif event_type == "response.output_text.done":
        transcript = event.get("text")
        role = "assistant"

    if not isinstance(transcript, str):
        return

    cleaned = _clean_text(transcript)
    if not cleaned:
        return

    if role == "user":
        _extract_user_identity(memory, cleaned)

    memory.recent_events.append((role or "unknown", cleaned))
    memory.updated_at_monotonic = time.monotonic()


def build_memory_aware_instructions(base_instructions: str, memory: VoiceMemoryState) -> str:
    base = (base_instructions or "").strip()
    if not base:
        return ""

    lines: list[str] = []
    if memory.preferred_name:
        lines.append(f"User preferred name: {memory.preferred_name}.")

    recent = list(memory.recent_events)[-6:]
    if recent:
        lines.append("Recent conversation context:")
        for role, text in recent:
            who = "User" if role == "user" else "Assistant"
            clipped = text[:180]
            lines.append(f"{who}: {clipped}")

    if not lines:
        return base

    return (
        f"{base}\n\n"
        "Conversation continuity memory:\n"
        f"{chr(10).join(lines)}\n"
        "If memory seems uncertain, ask a brief clarification question."
    )


def _extract_user_identity(memory: VoiceMemoryState, transcript: str) -> None:
    for pattern in (_CALL_ME_PATTERN, _MY_NAME_PATTERN):
        match = pattern.search(transcript)
        if not match:
            continue
        candidate = _clean_name(match.group(1))
        if candidate:
            memory.preferred_name = candidate
        return


def _clean_name(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if len(text) > 32:
        text = text[:32].rstrip()
    return text


def _clean_text(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    text = _WHITESPACE_PATTERN.sub(" ", text)
    return text
