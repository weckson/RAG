from __future__ import annotations

import math
from dataclasses import dataclass

from src.common.models import Side, Signal
from src.risk.position_sizing import fixed_notional_quantity


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    qty: int = 0


class RiskEngine:
    def __init__(
        self,
        max_positions: int,
        max_daily_loss_usd: float,
        max_order_notional_usd: float,
        max_total_notional_usd: float,
    ) -> None:
        self.max_positions = max_positions
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_order_notional_usd = max_order_notional_usd
        self.max_total_notional_usd = max_total_notional_usd

    def evaluate(
        self,
        signal: Signal,
        price: float,
        positions: dict[str, int],
        mark_prices: dict[str, float],
        daily_pnl_usd: float,
    ) -> RiskDecision:
        if daily_pnl_usd <= -abs(self.max_daily_loss_usd):
            return RiskDecision(False, "DAILY_LOSS_LIMIT_REACHED")

        if price <= 0:
            return RiskDecision(False, "INVALID_PRICE")

        long_positions = sum(1 for qty in positions.values() if qty > 0)
        current_qty = positions.get(signal.symbol, 0)

        if signal.side == Side.BUY:
            if current_qty > 0:
                return RiskDecision(False, "ALREADY_LONG")
            if long_positions >= self.max_positions:
                return RiskDecision(False, "MAX_POSITIONS_REACHED")
        else:
            if current_qty <= 0:
                return RiskDecision(False, "NO_LONG_TO_EXIT")
            return RiskDecision(True, "EXIT_ALLOWED", qty=abs(current_qty))

        current_total_notional = 0.0
        for symbol, qty in positions.items():
            if qty <= 0:
                continue
            mark = mark_prices.get(symbol, price)
            current_total_notional += qty * max(mark, 0.0)

        remaining_total = self.max_total_notional_usd - current_total_notional
        if remaining_total <= 0:
            return RiskDecision(False, "MAX_TOTAL_NOTIONAL_REACHED")

        allowed_notional = min(self.max_order_notional_usd, remaining_total)
        base_qty = fixed_notional_quantity(price=price, max_notional_usd=allowed_notional)
        if base_qty <= 0:
            return RiskDecision(False, "ORDER_NOTIONAL_TOO_SMALL")

        confidence = max(0.05, min(1.0, signal.confidence))
        qty = max(1, math.floor(base_qty * confidence))

        return RiskDecision(True, "OK", qty=qty)
