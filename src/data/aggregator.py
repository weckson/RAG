from __future__ import annotations

import logging
from dataclasses import dataclass

from src.common.models import Bar, Tick
from src.common.timeutil import interval_end, interval_start

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CurrentBar:
    open: float
    high: float
    low: float
    close: float
    volume: float
    start_ts_ms: int
    end_ts_ms: int


class BarAggregator:
    def __init__(self, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self.interval_seconds = interval_seconds
        self._bars: dict[str, _CurrentBar] = {}

    def process_tick(self, tick: Tick) -> list[Bar]:
        finished: list[Bar] = []
        bar_start = interval_start(tick.ts_ms, self.interval_seconds)
        bar_end = interval_end(bar_start, self.interval_seconds)
        current = self._bars.get(tick.symbol)

        if current is None:
            self._bars[tick.symbol] = _CurrentBar(
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=tick.size,
                start_ts_ms=bar_start,
                end_ts_ms=bar_end,
            )
            return finished

        if tick.ts_ms < current.start_ts_ms:
            logger.warning(
                "out-of-order tick dropped symbol=%s tick_ts=%s current_start=%s",
                tick.symbol,
                tick.ts_ms,
                current.start_ts_ms,
            )
            return finished

        if bar_start > current.start_ts_ms:
            finished.append(
                Bar(
                    symbol=tick.symbol,
                    open=current.open,
                    high=current.high,
                    low=current.low,
                    close=current.close,
                    volume=current.volume,
                    start_ts_ms=current.start_ts_ms,
                    end_ts_ms=current.end_ts_ms,
                )
            )
            self._bars[tick.symbol] = _CurrentBar(
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=tick.size,
                start_ts_ms=bar_start,
                end_ts_ms=bar_end,
            )
            return finished

        current.high = max(current.high, tick.price)
        current.low = min(current.low, tick.price)
        current.close = tick.price
        current.volume += tick.size
        return finished

    def flush_all(self) -> list[Bar]:
        out: list[Bar] = []
        for symbol, current in list(self._bars.items()):
            out.append(
                Bar(
                    symbol=symbol,
                    open=current.open,
                    high=current.high,
                    low=current.low,
                    close=current.close,
                    volume=current.volume,
                    start_ts_ms=current.start_ts_ms,
                    end_ts_ms=current.end_ts_ms,
                )
            )
        self._bars.clear()
        return out
