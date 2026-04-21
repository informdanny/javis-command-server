#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx


DEFAULT_SEQUENCE = [
    "ping",
    "status",
    "set mode muted",
    "set mode armed",
    "turn on the light",
]


def load_api_key_from_env_file(env_file: str) -> str | None:
    path = Path(env_file)
    if not path.is_file():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "AGENT_API_KEY":
            return value.strip().strip("'").strip('"')
    return None


def send_command(base_url: str, api_key: str, device_id: str, command: str, event_id: str | None = None) -> tuple[int, dict]:
    payload = {
        "event_id": event_id or str(uuid4()),
        "device_id": device_id,
        "source": "bridge",
        "trigger": "direct_test",
        "command_text": command,
        "ts_ms": int(time.time() * 1000),
        "meta": {"simulator": "device_simulator.py"},
    }
    headers = {"x-agent-key": api_key}
    response = httpx.post(f"{base_url.rstrip('/')}/v1/commands", json=payload, headers=headers, timeout=20.0)
    return response.status_code, response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate an ESP32 client from your laptop")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.getenv("AGENT_API_KEY"), help="Defaults to AGENT_API_KEY env var")
    parser.add_argument("--env-file", default=".env", help="Fallback .env path if AGENT_API_KEY not set")
    parser.add_argument("--device-id", default="esp32-sim-1")
    parser.add_argument("--command", help="Send a single command")
    parser.add_argument("--sequence", action="store_true", help="Run default sequence")
    parser.add_argument("--duplicate-test", action="store_true", help="Send the same event_id twice")
    args = parser.parse_args()

    if not args.api_key:
        args.api_key = load_api_key_from_env_file(args.env_file)

    if not args.api_key:
        raise SystemExit(
            f"Missing API key. Set AGENT_API_KEY, pass --api-key, or add AGENT_API_KEY to {args.env_file}."
        )

    try:
        if args.command:
            status, body = send_command(args.url, args.api_key, args.device_id, args.command)
            print(f"HTTP {status}")
            print(json.dumps(body, indent=2))
            return 0 if status == 200 else 1

        if args.duplicate_test:
            dup_id = str(uuid4())
            first_status, first_body = send_command(args.url, args.api_key, args.device_id, "ping", event_id=dup_id)
            second_status, second_body = send_command(args.url, args.api_key, args.device_id, "ping", event_id=dup_id)
            print("first")
            print(f"HTTP {first_status}")
            print(json.dumps(first_body, indent=2))
            print("second")
            print(f"HTTP {second_status}")
            print(json.dumps(second_body, indent=2))
            return 0 if second_body.get("status") == "ignored" else 1

        commands = DEFAULT_SEQUENCE if args.sequence or not args.command else [args.command]
        for idx, cmd in enumerate(commands, start=1):
            status, body = send_command(args.url, args.api_key, args.device_id, cmd)
            print(f"[{idx}] command={cmd!r} HTTP {status}")
            print(json.dumps(body, indent=2))
            print("-")
        return 0
    except httpx.ConnectError:
        raise SystemExit(
            f"Could not connect to {args.url}. Start the server first with:\n"
            "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
        )


if __name__ == "__main__":
    raise SystemExit(main())
