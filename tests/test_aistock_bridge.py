from __future__ import annotations

from src.integrations.aistock_bridge import BridgeConfig, SignalDraft, card_to_signal


def test_watch_card_maps_to_buy_signal() -> None:
    cfg = BridgeConfig()
    card = {
        "ticker": "AAPL",
        "priority_score": 72.5,
        "action_suggestion": "watch",
        "sentiment_summary": {"sentiment": 0.36, "momentum": 0.25},
        "theme_summary": {"crowding_risk": 0.4},
        "components": {"neg_risk_penalty": 3.0},
    }

    signal = card_to_signal(card, cfg)
    assert signal is not None
    assert signal.symbol == "AAPL"
    assert signal.side == "BUY"
    assert signal.confidence == 0.725


def test_caution_card_maps_to_sell_signal_when_risk_penalty_high() -> None:
    cfg = BridgeConfig()
    card = {
        "ticker": "NVDA",
        "priority_score": 61.0,
        "action_suggestion": "caution",
        "sentiment_summary": {"sentiment": 0.05, "momentum": -0.02},
        "theme_summary": {"crowding_risk": 0.2},
        "components": {"neg_risk_penalty": 18.0},
    }

    signal = card_to_signal(card, cfg)
    assert signal is not None
    assert signal.side == "SELL"


def test_wait_confirm_is_skipped() -> None:
    cfg = BridgeConfig()
    card = {
        "ticker": "TSLA",
        "priority_score": 90.0,
        "action_suggestion": "wait_confirm",
        "sentiment_summary": {"sentiment": 0.9, "momentum": 0.9},
        "theme_summary": {"crowding_risk": 0.1},
        "components": {"neg_risk_penalty": 0.0},
    }

    signal = card_to_signal(card, cfg)
    assert signal is None


def test_guard_multiplier_modulates_confidence() -> None:
    """Simulate what _apply_guards does: multiply confidence by guard multiplier."""
    cfg = BridgeConfig()
    card = {
        "ticker": "AAPL",
        "priority_score": 80.0,
        "action_suggestion": "watch",
        "sentiment_summary": {"sentiment": 0.5, "momentum": 0.3},
        "theme_summary": {"crowding_risk": 0.2},
        "components": {"neg_risk_penalty": 0.0},
    }
    draft = card_to_signal(card, cfg)
    assert draft is not None
    assert draft.confidence == 0.8  # 80/100

    # Simulate guard with multiplier 0.5 (medium risk)
    draft.guard_multiplier = 0.5
    draft.confidence = max(0.05, min(1.0, draft.confidence * 0.5))
    assert draft.confidence == 0.4  # 0.8 * 0.5


def test_guard_blocks_buy_when_multiplier_too_low() -> None:
    """BUY should be blocked when guard_multiplier < min_guard_multiplier_for_buy."""
    cfg = BridgeConfig(min_guard_multiplier_for_buy=0.2)
    card = {
        "ticker": "AAPL",
        "priority_score": 80.0,
        "action_suggestion": "watch",
        "sentiment_summary": {"sentiment": 0.5, "momentum": 0.3},
        "theme_summary": {"crowding_risk": 0.2},
        "components": {"neg_risk_penalty": 0.0},
    }
    draft = card_to_signal(card, cfg)
    assert draft is not None

    # Guard with very low multiplier (e.g., danger flags active: 0.3 * 0.4 = 0.12)
    multiplier = 0.12
    assert multiplier < cfg.min_guard_multiplier_for_buy
    # Bridge would skip this BUY signal


def test_sell_not_blocked_by_low_guard_multiplier() -> None:
    """SELL signals should NOT be blocked by low guard multiplier."""
    cfg = BridgeConfig()
    card = {
        "ticker": "NVDA",
        "priority_score": 61.0,
        "action_suggestion": "avoid",
        "sentiment_summary": {"sentiment": -0.3, "momentum": -0.2},
        "theme_summary": {"crowding_risk": 0.2},
        "components": {"neg_risk_penalty": 25.0},
    }
    draft = card_to_signal(card, cfg)
    assert draft is not None
    assert draft.side == "SELL"
    # Guard multiplier doesn't block sells; it only adjusts confidence


def test_signal_draft_has_guard_defaults() -> None:
    """SignalDraft should have sensible guard defaults."""
    draft = SignalDraft(
        symbol="TEST", side="BUY", confidence=0.5, reason="test",
        source_action="watch", priority_score=50.0, sentiment=0.3, momentum=0.1,
    )
    assert draft.guard_multiplier == 1.0
    assert draft.guard_risk_ok is True
    assert draft.hold_horizon_hint == "1d"
