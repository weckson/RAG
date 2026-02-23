from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class RateLimiter:
    max_calls: int
    period_seconds: float
    _calls: deque[float] = field(default_factory=deque)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            while self._calls and now - self._calls[0] > self.period_seconds:
                self._calls.popleft()
            if len(self._calls) < self.max_calls:
                self._calls.append(now)
                return
            wait_for = self.period_seconds - (now - self._calls[0])
        await asyncio.sleep(max(wait_for, 0.0))
        await self.acquire()
