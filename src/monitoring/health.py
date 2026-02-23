from __future__ import annotations

import asyncio
from dataclasses import asdict

from src.common.models import HealthSnapshot


class HealthTracker:
    def __init__(self, snapshot: HealthSnapshot) -> None:
        self._snapshot = snapshot
        self._lock = asyncio.Lock()

    async def update(
        self,
        *,
        control_server_ready: bool | None = None,
        ibkr_connected: bool | None = None,
        signal_queue_size: int | None = None,
        last_signal_ts_ms: int | None = None,
        kill_switch: bool | None = None,
    ) -> None:
        async with self._lock:
            if control_server_ready is not None:
                self._snapshot.control_server_ready = control_server_ready
            if ibkr_connected is not None:
                self._snapshot.ibkr_connected = ibkr_connected
            if signal_queue_size is not None:
                self._snapshot.signal_queue_size = signal_queue_size
            if last_signal_ts_ms is not None:
                self._snapshot.last_signal_ts_ms = last_signal_ts_ms
            if kill_switch is not None:
                self._snapshot.kill_switch = kill_switch

    async def get_snapshot(self) -> dict[str, object]:
        async with self._lock:
            return asdict(self._snapshot)
