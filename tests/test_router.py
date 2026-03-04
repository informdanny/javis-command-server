from app.router import route_command
from app.schemas import Intent, Status


def test_ping_route():
    result = route_command("ping")
    assert result.intent == Intent.ping
    assert result.status == Status.ok
    assert result.reply_text == "pong"


def test_status_route_with_spacing_and_case():
    result = route_command("   StAtUs  ")
    assert result.intent == Intent.status
    assert result.status == Status.ok


def test_set_mode_route():
    result = route_command("set mode muted")
    assert result.intent == Intent.set_mode
    assert result.status == Status.ok
    assert result.action_type == "set_mode"
    assert result.action_value == "muted"


def test_unknown_route():
    result = route_command("turn on the lights")
    assert result.intent == Intent.unknown
    assert result.status == Status.ignored
