from __future__ import annotations

from dataclasses import dataclass

from src.common.models import Bar, Side
from src.strategy.base import Strategy


@dataclass(slots=True)
class BacktestResult:
    trades: int
    pnl_usd: float


def run_backtest(strategy: Strategy, bars: list[Bar], notional_per_trade: float = 2000.0) -> BacktestResult:
    position_qty = 0.0
    cash = 0.0
    trades = 0

    for bar in bars:
        signals = strategy.on_bar(bar)
        for signal in signals:
            qty = notional_per_trade / max(bar.close, 1e-6)
            if signal.side == Side.BUY and position_qty == 0:
                position_qty += qty
                cash -= qty * bar.close
                trades += 1
            elif signal.side == Side.SELL and position_qty > 0:
                cash += position_qty * bar.close
                position_qty = 0
                trades += 1

    if bars and position_qty > 0:
        cash += position_qty * bars[-1].close

    return BacktestResult(trades=trades, pnl_usd=cash)
