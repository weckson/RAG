from __future__ import annotations

from datetime import datetime, timezone


def now_utc_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def interval_start(ts_ms: int, interval_seconds: int) -> int:
    interval_ms = interval_seconds * 1000
    return ts_ms - (ts_ms % interval_ms)


def interval_end(start_ts_ms: int, interval_seconds: int) -> int:
    return start_ts_ms + interval_seconds * 1000 - 1
