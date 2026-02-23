from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class RetryPolicy:
    initial_delay: float = 1.0
    max_delay: float = 30.0
    factor: float = 2.0
    max_retries: int = 20

    async def sleep_for_attempt(
        self, attempt: int, on_sleep: Callable[[int, float], None] | None = None
    ) -> None:
        delay = min(self.initial_delay * (self.factor ** max(0, attempt - 1)), self.max_delay)
        if on_sleep:
            on_sleep(attempt, delay)
        await asyncio.sleep(delay)
