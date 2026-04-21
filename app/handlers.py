from __future__ import annotations

import time


def build_status_reply(start_time_monotonic: float, service_name: str, version: str, desired_mode: str) -> str:
    uptime_seconds = int(time.monotonic() - start_time_monotonic)
    return f"{service_name} healthy, uptime={uptime_seconds}s, version={version}, desired_mode={desired_mode}"
