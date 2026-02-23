from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeMetrics:
    bars_processed: int = 0
    signals_generated: int = 0
    orders_submitted: int = 0
    errors: int = 0
