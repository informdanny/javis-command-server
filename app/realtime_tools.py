from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.handlers import build_status_reply
from app.router import route_command
from app.web_search import search_web


@dataclass(frozen=True)
class RealtimeToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class RealtimeToolResult:
    call_id: str
    name: str
    output: dict[str, Any]
    requested_mode: str | None = None


def extract_realtime_tool_calls(event: dict[str, Any]) -> list[RealtimeToolCall]:
    event_type = event.get("type")
    if event_type == "response.function_call_arguments.done":
        tool_call = _tool_call_from_parts(
            call_id=event.get("call_id"),
            name=event.get("name"),
            arguments=event.get("arguments"),
        )
        return [tool_call] if tool_call else []

    if event_type == "response.output_item.done":
        tool_call = _tool_call_from_item(event.get("item"))
        return [tool_call] if tool_call else []

    if event_type != "response.done":
        return []

    response = event.get("response")
    if not isinstance(response, dict):
        return []

    calls: list[RealtimeToolCall] = []
    for item in response.get("output") or []:
        tool_call = _tool_call_from_item(item)
        if tool_call:
            calls.append(tool_call)
    return calls


def execute_realtime_tool_call(
    tool_call: RealtimeToolCall,
    *,
    service_name: str,
    version: str,
    start_time_monotonic: float,
    desired_mode: str,
    web_search_timeout_seconds: float = 8.0,
    web_search_max_results: int = 3,
) -> RealtimeToolResult:
    if tool_call.name == "get_agent_status":
        reply_text = build_status_reply(
            start_time_monotonic=start_time_monotonic,
            service_name=service_name,
            version=version,
            desired_mode=desired_mode,
        )
        return RealtimeToolResult(
            call_id=tool_call.call_id,
            name=tool_call.name,
            output={
                "ok": True,
                "service_status": "ok",
                "desired_mode": desired_mode,
                "reply_text": reply_text,
            },
        )

    if tool_call.name == "set_agent_mode":
        mode = tool_call.arguments.get("mode")
        if not isinstance(mode, str) or mode not in {"armed", "muted"}:
            return RealtimeToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                output={
                    "ok": False,
                    "error": "mode must be 'armed' or 'muted'",
                    "desired_mode": desired_mode,
                },
            )

        route = route_command(f"set mode {mode}")
        return RealtimeToolResult(
            call_id=tool_call.call_id,
            name=tool_call.name,
            requested_mode=mode,
            output={
                "ok": True,
                "reply_text": route.reply_text,
                "intent": route.intent.value,
                "action": {"type": route.action_type, "value": route.action_value},
                "desired_mode": mode,
                "device_sync": "pending",
                "note": "Server desired mode updated; ESP32 mode sync is not wired yet.",
            },
        )

    if tool_call.name == "search_web":
        query = tool_call.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return RealtimeToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                output={
                    "ok": False,
                    "error": "query must be a non-empty string",
                    "desired_mode": desired_mode,
                },
            )

        max_results = web_search_max_results
        raw_max_results = tool_call.arguments.get("max_results")
        if isinstance(raw_max_results, (int, float, str)):
            try:
                max_results = int(raw_max_results)
            except (TypeError, ValueError):
                max_results = web_search_max_results
        max_results = max(1, min(max_results, 8))

        output = search_web(
            query=query,
            max_results=max_results,
            timeout_seconds=web_search_timeout_seconds,
        )
        output["desired_mode"] = desired_mode
        return RealtimeToolResult(
            call_id=tool_call.call_id,
            name=tool_call.name,
            output=output,
        )

    return RealtimeToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        output={
            "ok": False,
            "error": f"unsupported tool: {tool_call.name}",
            "desired_mode": desired_mode,
        },
    )


def build_function_output_event(result: RealtimeToolResult) -> dict[str, Any]:
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": result.call_id,
            "output": json.dumps(result.output),
        },
    }


def _tool_call_from_item(item: Any) -> RealtimeToolCall | None:
    if not isinstance(item, dict) or item.get("type") != "function_call":
        return None
    return _tool_call_from_parts(
        call_id=item.get("call_id"),
        name=item.get("name"),
        arguments=item.get("arguments"),
    )


def _tool_call_from_parts(*, call_id: Any, name: Any, arguments: Any) -> RealtimeToolCall | None:
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    return RealtimeToolCall(call_id=call_id, name=name, arguments=_coerce_arguments(arguments))


def _coerce_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str) or not arguments.strip():
        return {}
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return {"_raw_arguments": arguments}
    if isinstance(payload, dict):
        return payload
    return {"_value": payload}
