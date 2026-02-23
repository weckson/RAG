from src.common.models import Side, Signal
from src.risk.rules import RiskEngine


def _signal(side: Side) -> Signal:
    return Signal(
        id="sig_1",
        symbol="AAPL",
        side=side,
        confidence=0.8,
        reason="test",
        ts_ms=1,
    )


def test_buy_allowed_with_qty() -> None:
    risk = RiskEngine(
        max_positions=5,
        max_daily_loss_usd=200,
        max_order_notional_usd=2000,
        max_total_notional_usd=8000,
    )
    decision = risk.evaluate(
        signal=_signal(Side.BUY),
        price=100.0,
        positions={},
        mark_prices={},
        daily_pnl_usd=0.0,
    )
    assert decision.allowed
    assert decision.qty == 20


def test_buy_rejected_when_already_long() -> None:
    risk = RiskEngine(5, 200, 2000, 8000)
    decision = risk.evaluate(
        signal=_signal(Side.BUY),
        price=100.0,
        positions={"AAPL": 10},
        mark_prices={"AAPL": 100.0},
        daily_pnl_usd=0.0,
    )
    assert not decision.allowed
    assert decision.reason == "ALREADY_LONG"


def test_sell_rejected_when_no_position() -> None:
    risk = RiskEngine(5, 200, 2000, 8000)
    decision = risk.evaluate(
        signal=_signal(Side.SELL),
        price=100.0,
        positions={},
        mark_prices={},
        daily_pnl_usd=0.0,
    )
    assert not decision.allowed
    assert decision.reason == "NO_LONG_TO_EXIT"


def test_daily_loss_limit_blocks_orders() -> None:
    risk = RiskEngine(5, 200, 2000, 8000)
    decision = risk.evaluate(
        signal=_signal(Side.BUY),
        price=100.0,
        positions={},
        mark_prices={},
        daily_pnl_usd=-250.0,
    )
    assert not decision.allowed
    assert decision.reason == "DAILY_LOSS_LIMIT_REACHED"
