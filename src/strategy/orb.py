from __future__ import annotations

from src.common.models import Bar, Signal
from src.strategy.base import Strategy


class ORBStrategy(Strategy):
    """Placeholder for opening range breakout strategy."""

    def on_bar(self, bar: Bar) -> list[Signal]:
        return []
