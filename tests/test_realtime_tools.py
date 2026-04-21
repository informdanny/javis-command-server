from app.realtime_tools import build_function_output_event, execute_realtime_tool_call, extract_realtime_tool_calls


def test_extract_realtime_tool_calls_from_response_done():
    event = {
        "type": "response.done",
        "response": {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "set_agent_mode",
                    "arguments": '{"mode":"muted"}',
                }
            ]
        },
    }

    calls = extract_realtime_tool_calls(event)

    assert len(calls) == 1
    assert calls[0].call_id == "call_123"
    assert calls[0].name == "set_agent_mode"
    assert calls[0].arguments == {"mode": "muted"}


def test_extract_realtime_tool_calls_from_argument_done():
    event = {
        "type": "response.function_call_arguments.done",
        "call_id": "call_456",
        "name": "get_agent_status",
        "arguments": "{}",
    }

    calls = extract_realtime_tool_calls(event)

    assert len(calls) == 1
    assert calls[0].call_id == "call_456"
    assert calls[0].name == "get_agent_status"
    assert calls[0].arguments == {}


def test_execute_realtime_tool_call_returns_truthful_set_mode_result():
    tool_call = extract_realtime_tool_calls(
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call_789",
            "name": "set_agent_mode",
            "arguments": '{"mode":"armed"}',
        }
    )[0]

    result = execute_realtime_tool_call(
        tool_call,
        service_name="javis-command-server",
        version="0.2.0",
        start_time_monotonic=0.0,
        desired_mode="muted",
    )

    assert result.requested_mode == "armed"
    assert result.output["ok"] is True
    assert result.output["desired_mode"] == "armed"
    assert result.output["device_sync"] == "pending"


def test_build_function_output_event_wraps_json_output():
    tool_call = extract_realtime_tool_calls(
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call_999",
            "name": "get_agent_status",
            "arguments": "{}",
        }
    )[0]
    result = execute_realtime_tool_call(
        tool_call,
        service_name="javis-command-server",
        version="0.2.0",
        start_time_monotonic=0.0,
        desired_mode="armed",
    )

    event = build_function_output_event(result)

    assert event["type"] == "conversation.item.create"
    assert event["item"]["type"] == "function_call_output"
    assert event["item"]["call_id"] == "call_999"
