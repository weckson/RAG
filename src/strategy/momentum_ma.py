from __future__ import annotations

from collections import defaultdict, deque

from src.common.ids import new_signal_id
from src.common.models import Bar, Side, Signal
from src.common.timeutil import now_utc_ms
from src.strategy.base import Strategy
from src.strategy.features import simple_moving_average


class MomentumMAStrategy(Strategy):
    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=slow_period + 2)
        )

    def on_bar(self, bar: Bar) -> list[Signal]:
        closes = self.history[bar.symbol]
        closes.append(bar.close)
        values = list(closes)

        fast = simple_moving_average(values, self.fast_period)
        slow = simple_moving_average(values, self.slow_period)
        if fast is None or slow is None:
            return []

        prev_values = values[:-1]
        prev_fast = simple_moving_average(prev_values, self.fast_period)
        prev_slow = simple_moving_average(prev_values, self.slow_period)
        if prev_fast is None or prev_slow is None:
            return []

        if prev_fast <= prev_slow and fast > slow:
            confidence = min(abs(fast - slow) / max(slow, 1e-6), 1.0)
            return [
                Signal(
                    id=new_signal_id(bar.symbol),
                    symbol=bar.symbol,
                    side=Side.BUY,
                    confidence=confidence,
                    reason=f"MA_CROSS_UP_{self.fast_period}_{self.slow_period}",
                    ts_ms=now_utc_ms(),
                )
            ]

        if prev_fast >= prev_slow and fast < slow:
            confidence = min(abs(fast - slow) / max(slow, 1e-6), 1.0)
            return [
                Signal(
                    id=new_signal_id(bar.symbol),
                    symbol=bar.symbol,
                    side=Side.SELL,
                    confidence=confidence,
                    reason=f"MA_CROSS_DOWN_{self.fast_period}_{self.slow_period}",
                    ts_ms=now_utc_ms(),
                )
            ]

        return []
