#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
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
        "meta": {"simulator": "local_test_harness.py"},
    }
    headers = {"x-agent-key": api_key}
    response = httpx.post(f"{base_url.rstrip('/')}/v1/commands", json=payload, headers=headers, timeout=20.0)
    return response.status_code, response.json()


def wait_for_health(url: str, timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = httpx.get(f"{url.rstrip('/')}/healthz", timeout=1.5)
            if response.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def run_sequence(url: str, api_key: str, device_id: str) -> None:
    for idx, command in enumerate(DEFAULT_SEQUENCE, start=1):
        status, body = send_command(url, api_key, device_id, command)
        print(f"[{idx}] {command!r} -> HTTP {status} status={body.get('status')} intent={body.get('intent')}")


def run_duplicate_test(url: str, api_key: str, device_id: str) -> None:
    dup_id = str(uuid4())
    _, first_body = send_command(url, api_key, device_id, "ping", event_id=dup_id)
    _, second_body = send_command(url, api_key, device_id, "ping", event_id=dup_id)
    print(f"duplicate test -> first={first_body.get('status')} second={second_body.get('status')}")
    if second_body.get("status") != "ignored":
        raise RuntimeError("Duplicate guard failed: second request was not ignored.")


def start_local_server(url: str, env: dict[str, str]) -> subprocess.Popen:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 8000)
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", port]
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start local server if needed, then run simulator tests.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.getenv("AGENT_API_KEY"))
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--device-id", default="esp32-sim-1")
    parser.add_argument("--keep-server", action="store_true", help="Keep spawned local server running after tests.")
    args = parser.parse_args()

    api_key = args.api_key or load_api_key_from_env_file(args.env_file)
    if not api_key:
        raise SystemExit(
            f"Missing API key. Set AGENT_API_KEY, pass --api-key, or add AGENT_API_KEY to {args.env_file}."
        )

    spawned: subprocess.Popen | None = None
    env = os.environ.copy()
    env["AGENT_API_KEY"] = api_key

    try:
        if not wait_for_health(args.url, timeout_seconds=1.5):
            print("Local server not detected; starting it now...")
            spawned = start_local_server(args.url, env)
            if not wait_for_health(args.url):
                raise RuntimeError("Server did not become healthy in time.")
        else:
            print("Using already-running local server.")

        print("healthz:", json.dumps(httpx.get(f"{args.url.rstrip('/')}/healthz", timeout=5.0).json()))
        run_sequence(args.url, api_key, args.device_id)
        run_duplicate_test(args.url, api_key, args.device_id)
        print("Local harness passed.")
        return 0
    finally:
        if spawned and not args.keep_server:
            spawned.send_signal(signal.SIGTERM)
            try:
                spawned.wait(timeout=8)
            except subprocess.TimeoutExpired:
                spawned.kill()


if __name__ == "__main__":
    raise SystemExit(main())
