from __future__ import annotations

from src.backtest.engine import BacktestResult


def render_report(result: BacktestResult) -> str:
    return f"trades={result.trades} pnl_usd={result.pnl_usd:.2f}"
