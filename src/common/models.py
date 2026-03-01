from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(slots=True)
class Tick:
    symbol: str
    price: float
    size: float
    ts_ms: int


@dataclass(slots=True)
class Bar:
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    start_ts_ms: int
    end_ts_ms: int


@dataclass(slots=True)
class Signal:
    id: str
    symbol: str
    side: Side
    confidence: float
    reason: str
    ts_ms: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderEvent:
    signal_id: str
    symbol: str
    side: Side
    qty: int
    order_id: int | None
    status: str
    reason: str = ""
    ts_ms: int = 0


@dataclass(slots=True)
class FillEvent:
    order_id: int
    symbol: str
    side: Side
    qty: float
    avg_price: float
    ts_ms: int


@dataclass(slots=True)
class HealthSnapshot:
    control_server_ready: bool = False
    ibkr_connected: bool = False
    signal_queue_size: int = 0
    last_signal_ts_ms: int | None = None
    kill_switch: bool = False
    trading_mode: Literal["paper", "live"] = "paper"
    app_env: str = "dev"
    extra: dict[str, str | int | float | bool] = field(default_factory=dict)
