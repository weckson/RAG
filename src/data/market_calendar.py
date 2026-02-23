from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


class MarketCalendar:
    def __init__(self, tz_name: str = "America/New_York") -> None:
        self.tz = ZoneInfo(tz_name)

    def is_regular_session(self, now: datetime | None = None) -> bool:
        dt = now.astimezone(self.tz) if now else datetime.now(self.tz)
        if dt.weekday() >= 5:
            return False
        market_open = time(hour=9, minute=30)
        market_close = time(hour=16, minute=0)
        current = dt.time()
        return market_open <= current <= market_close
