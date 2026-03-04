#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from time import time
from uuid import uuid4

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test command to Javis command server")
    parser.add_argument("--url", required=True, help="Base URL, e.g. https://javis-command-server.onrender.com")
    parser.add_argument("--api-key", required=True, help="x-agent-key value")
    parser.add_argument("--device-id", default="bridge-local")
    parser.add_argument("--command", default="ping")
    args = parser.parse_args()

    payload = {
        "event_id": str(uuid4()),
        "device_id": args.device_id,
        "source": "bridge",
        "trigger": "direct_test",
        "command_text": args.command,
        "ts_ms": int(time() * 1000),
        "meta": {"sent_by": "tools/send_test_command.py"},
    }

    headers = {"x-agent-key": args.api_key}
    response = httpx.post(f"{args.url.rstrip('/')}/v1/commands", headers=headers, json=payload, timeout=20.0)
    print(f"HTTP {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
