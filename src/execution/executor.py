from __future__ import annotations

import logging

from src.common.models import FillEvent, OrderEvent, Side, Signal
from src.common.timeutil import now_utc_ms
from src.data.store import SQLiteStore
from src.execution.broker_state import BrokerState
from src.execution.ibkr_client import IBKRClient
from src.execution.order_factory import create_bracket_orders, create_market_order
from src.monitoring.notifier import Notifier
from src.risk.kill_switch import KillSwitch
from src.risk.rules import RiskEngine

logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(
        self,
        ibkr: IBKRClient,
        risk: RiskEngine,
        store: SQLiteStore,
        notifier: Notifier,
        kill_switch: KillSwitch,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> None:
        self.ibkr = ibkr
        self.risk = risk
        self.store = store
        self.notifier = notifier
        self.kill_switch = kill_switch
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

        self.state = BrokerState()
        self.mark_prices: dict[str, float] = {}
        self.daily_pnl_usd: float = 0.0

    def update_mark(self, symbol: str, price: float) -> None:
        self.mark_prices[symbol] = price

    async def refresh_broker_state(self) -> None:
        positions = await self.ibkr.get_positions()
        self.state.update_positions(positions)
        account = await self.ibkr.get_account_values()
        realized = account.get("RealizedPnL", 0.0)
        unrealized = account.get("UnrealizedPnL", 0.0)
        self.daily_pnl_usd = realized + unrealized

    async def process_signal(self, signal: Signal) -> None:
        ts_ms = now_utc_ms()
        price = self.mark_prices.get(signal.symbol)
        if price is None:
            event = OrderEvent(
                signal_id=signal.id,
                symbol=signal.symbol,
                side=signal.side,
                qty=0,
                order_id=None,
                status="REJECTED",
                reason="MISSING_MARK_PRICE",
                ts_ms=ts_ms,
            )
            self.store.insert_order(event)
            return

        if self.kill_switch.is_active():
            event = OrderEvent(
                signal_id=signal.id,
                symbol=signal.symbol,
                side=signal.side,
                qty=0,
                order_id=None,
                status="REJECTED",
                reason="KILL_SWITCH_ACTIVE",
                ts_ms=ts_ms,
            )
            self.store.insert_order(event)
            return

        decision = self.risk.evaluate(
            signal=signal,
            price=price,
            positions=self.state.positions,
            mark_prices=self.mark_prices,
            daily_pnl_usd=self.daily_pnl_usd,
        )
        if not decision.allowed:
            event = OrderEvent(
                signal_id=signal.id,
                symbol=signal.symbol,
                side=signal.side,
                qty=0,
                order_id=None,
                status="REJECTED",
                reason=decision.reason,
                ts_ms=ts_ms,
            )
            self.store.insert_order(event)
            return

        try:
            if signal.side == Side.BUY:
                order_id = await self.ibkr.next_order_id()
                sl_pct, tp_pct = self._compute_bracket_params(signal)
                take_profit = price * (1 + tp_pct)
                stop_loss = price * (1 - sl_pct)
                orders = create_bracket_orders(
                    parent_order_id=order_id,
                    side=signal.side,
                    qty=decision.qty,
                    take_profit_price=take_profit,
                    stop_loss_price=stop_loss,
                )
                trades = await self.ibkr.place_orders(signal.symbol, orders)
                self.state.positions[signal.symbol] = self.state.position_qty(signal.symbol) + decision.qty
            else:
                order_id = await self.ibkr.next_order_id()
                orders = [create_market_order(order_id=order_id, side=signal.side, qty=decision.qty)]
                trades = await self.ibkr.place_orders(signal.symbol, orders)
                self.state.positions[signal.symbol] = max(
                    self.state.position_qty(signal.symbol) - decision.qty, 0
                )

            self.state.open_order_ids.add(order_id)
            event = OrderEvent(
                signal_id=signal.id,
                symbol=signal.symbol,
                side=signal.side,
                qty=decision.qty,
                order_id=order_id,
                status="SUBMITTED",
                reason="OK",
                ts_ms=ts_ms,
            )
            self.store.insert_order(event)
            await self.notifier.send(
                f"ORDER SUBMITTED {signal.symbol} {signal.side.value} qty={decision.qty} order_id={order_id}"
            )
            fills = self._persist_fills(signal.symbol, signal.side, trades)
            for fill in fills:
                await self.notifier.send(
                    f"FILL {fill.symbol} {fill.side.value} qty={fill.qty} avg_price={fill.avg_price} order_id={fill.order_id}"
                )
        except Exception as exc:
            logger.exception("order submit failed signal_id=%s err=%s", signal.id, exc)
            event = OrderEvent(
                signal_id=signal.id,
                symbol=signal.symbol,
                side=signal.side,
                qty=decision.qty,
                order_id=None,
                status="FAILED",
                reason=str(exc),
                ts_ms=now_utc_ms(),
            )
            self.store.insert_order(event)
            await self.notifier.send(f"ORDER FAILED {signal.symbol} err={exc}")

    def _compute_bracket_params(self, signal: Signal) -> tuple[float, float]:
        """Compute (stop_loss_pct, take_profit_pct) adapted by guard metadata.

        Guard multiplier ranges:
        - >= 0.8 (low risk): default stops
        - 0.5 - 0.8 (medium risk): widen by 50%
        - < 0.5 (high risk): widen by 100%

        Hold horizon adjustments:
        - "5m": tighten by 25% (scalp)
        - "30m": no adjustment
        - "1d": widen by 25% (swing)
        """
        base_sl = self.stop_loss_pct
        base_tp = self.take_profit_pct

        guard_multiplier = float(signal.meta.get("guard_multiplier", 1.0))
        horizon = str(signal.meta.get("hold_horizon_hint", "1d"))

        if guard_multiplier >= 0.8:
            risk_factor = 1.0
        elif guard_multiplier >= 0.5:
            risk_factor = 1.5
        else:
            risk_factor = 2.0

        if horizon == "5m":
            horizon_factor = 0.75
        elif horizon == "30m":
            horizon_factor = 1.0
        else:
            horizon_factor = 1.25

        return (base_sl * risk_factor * horizon_factor, base_tp * risk_factor * horizon_factor)

    def _persist_fills(self, symbol: str, side: Side, trades: list) -> list[FillEvent]:
        events: list[FillEvent] = []
        for trade in trades:
            for fill in getattr(trade, "fills", []) or []:
                qty = float(getattr(fill.execution, "shares", 0.0))
                avg_price = float(getattr(fill.execution, "avgPrice", 0.0))
                if qty <= 0 or avg_price <= 0:
                    continue
                event = FillEvent(
                    order_id=int(getattr(fill.execution, "orderId", 0)),
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    avg_price=avg_price,
                    ts_ms=now_utc_ms(),
                )
                self.store.insert_fill(event)
                events.append(event)
        return events
