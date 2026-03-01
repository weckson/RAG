from src.common.models import Side, Signal
from src.risk.rules import RiskEngine


def _signal(side: Side, confidence: float = 0.8) -> Signal:
    return Signal(
        id="sig_1",
        symbol="AAPL",
        side=side,
        confidence=confidence,
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
    # base_qty=20 (2000/100), scaled by confidence=0.8 → floor(20*0.8)=16
    assert decision.qty == 16


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


def test_buy_qty_scales_with_confidence() -> None:
    risk = RiskEngine(5, 200, 2000, 8000)

    # Full confidence: base_qty=20, floor(20*1.0)=20
    d1 = risk.evaluate(
        signal=_signal(Side.BUY, confidence=1.0),
        price=100.0, positions={}, mark_prices={}, daily_pnl_usd=0.0,
    )
    assert d1.allowed
    assert d1.qty == 20

    # Half confidence: floor(20*0.5)=10
    d2 = risk.evaluate(
        signal=_signal(Side.BUY, confidence=0.5),
        price=100.0, positions={}, mark_prices={}, daily_pnl_usd=0.0,
    )
    assert d2.allowed
    assert d2.qty == 10

    # Low confidence (0.1): floor(20*0.1)=2
    d3 = risk.evaluate(
        signal=_signal(Side.BUY, confidence=0.1),
        price=100.0, positions={}, mark_prices={}, daily_pnl_usd=0.0,
    )
    assert d3.allowed
    assert d3.qty == 2

    # Minimum floor: very low confidence still gives at least 1
    d4 = risk.evaluate(
        signal=_signal(Side.BUY, confidence=0.05),
        price=100.0, positions={}, mark_prices={}, daily_pnl_usd=0.0,
    )
    assert d4.allowed
    assert d4.qty == 1
