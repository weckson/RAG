from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


SignalSide = Literal["BUY", "SELL"]


@dataclass(slots=True)
class BridgeConfig:
    aistock_base_url: str = "http://127.0.0.1:8000"
    sentiment_engine_base_url: str = "http://127.0.0.1:8002"
    executor_base_url: str = "http://127.0.0.1:8080"
    executor_api_key: str = ""
    request_timeout_seconds: float = 10.0
    guard_timeout_seconds: float = 5.0
    poll_interval_seconds: int = 20
    dashboard_limit: int = 30
    min_priority_for_buy: float = 55.0
    min_sentiment_for_buy: float = 0.2
    min_momentum_for_buy: float = 0.05
    max_crowding_for_buy: float = 0.75
    max_sentiment_for_sell: float = -0.15
    max_momentum_for_sell: float = -0.1
    min_neg_risk_penalty_for_sell: float = 12.0
    cooldown_seconds: int = 180
    guard_enabled: bool = True
    min_guard_multiplier_for_buy: float = 0.2
    dry_run: bool = False

    @staticmethod
    def _normalize_url(value: str) -> str:
        return value.rstrip("/")

    def normalized(self) -> BridgeConfig:
        return BridgeConfig(
            aistock_base_url=self._normalize_url(self.aistock_base_url),
            sentiment_engine_base_url=self._normalize_url(self.sentiment_engine_base_url),
            executor_base_url=self._normalize_url(self.executor_base_url),
            executor_api_key=self.executor_api_key,
            request_timeout_seconds=self.request_timeout_seconds,
            guard_timeout_seconds=self.guard_timeout_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            dashboard_limit=self.dashboard_limit,
            min_priority_for_buy=self.min_priority_for_buy,
            min_sentiment_for_buy=self.min_sentiment_for_buy,
            min_momentum_for_buy=self.min_momentum_for_buy,
            max_crowding_for_buy=self.max_crowding_for_buy,
            max_sentiment_for_sell=self.max_sentiment_for_sell,
            max_momentum_for_sell=self.max_momentum_for_sell,
            min_neg_risk_penalty_for_sell=self.min_neg_risk_penalty_for_sell,
            cooldown_seconds=self.cooldown_seconds,
            guard_enabled=self.guard_enabled,
            min_guard_multiplier_for_buy=self.min_guard_multiplier_for_buy,
            dry_run=self.dry_run,
        )


@dataclass(slots=True)
class SignalDraft:
    symbol: str
    side: SignalSide
    confidence: float
    reason: str
    source_action: str
    priority_score: float
    sentiment: float
    momentum: float
    guard_multiplier: float = 1.0
    guard_risk_ok: bool = True
    hold_horizon_hint: str = "1d"


@dataclass(slots=True)
class BridgeStats:
    scanned_cards: int = 0
    generated_signals: int = 0
    submitted_signals: int = 0
    skipped_no_price: int = 0
    skipped_cooldown: int = 0
    skipped_already_held: int = 0
    skipped_guard_blocked: int = 0


@dataclass(slots=True)
class CooldownBook:
    _last_emit_ts: dict[tuple[str, SignalSide], float] = field(default_factory=dict)

    def allowed(self, symbol: str, side: SignalSide, cooldown_seconds: int, now_ts: float) -> bool:
        last = self._last_emit_ts.get((symbol, side))
        if last is None:
            return True
        return now_ts - last >= cooldown_seconds

    def mark(self, symbol: str, side: SignalSide, now_ts: float) -> None:
        self._last_emit_ts[(symbol, side)] = now_ts


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def card_to_signal(card: dict[str, Any], cfg: BridgeConfig) -> SignalDraft | None:
    symbol = _normalize_symbol(card.get("ticker"))
    if not symbol:
        return None

    action = str(card.get("action_suggestion", "")).strip().lower()
    if not action:
        return None

    priority = _as_float(card.get("priority_score"))
    sentiment_summary = card.get("sentiment_summary") or {}
    components = card.get("components") or {}
    theme_summary = card.get("theme_summary") or {}
    sentiment = _as_float(sentiment_summary.get("sentiment"))
    momentum = _as_float(sentiment_summary.get("momentum"))
    crowding = _as_float(theme_summary.get("crowding_risk"))
    neg_risk_penalty = _as_float(components.get("neg_risk_penalty"))

    side: SignalSide | None = None
    if action == "watch":
        if priority < cfg.min_priority_for_buy:
            return None
        if sentiment < cfg.min_sentiment_for_buy:
            return None
        if momentum < cfg.min_momentum_for_buy:
            return None
        if crowding > cfg.max_crowding_for_buy:
            return None
        side = "BUY"
    elif action in {"avoid", "caution"}:
        if not (
            sentiment <= cfg.max_sentiment_for_sell
            or momentum <= cfg.max_momentum_for_sell
            or neg_risk_penalty >= cfg.min_neg_risk_penalty_for_sell
        ):
            return None
        side = "SELL"
    else:
        return None

    confidence = _clamp(priority / 100.0, 0.05, 1.0)
    reason = (
        f"AISTOCK_{action.upper()}_P{priority:.1f}_S{sentiment:+.2f}_M{momentum:+.2f}"
    )

    return SignalDraft(
        symbol=symbol,
        side=side,
        confidence=confidence,
        reason=reason,
        source_action=action,
        priority_score=priority,
        sentiment=sentiment,
        momentum=momentum,
    )


class AIStockBridge:
    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg.normalized()
        self.cooldown = CooldownBook()
        self._client: httpx.AsyncClient | None = None
        # Embedded mode: direct access to executor state (no HTTP needed)
        self._direct_mark_prices: dict[str, float] | None = None
        self._direct_positions: dict[str, int] | None = None

    def set_direct_state(
        self,
        mark_prices: dict[str, float],
        positions: dict[str, int],
    ) -> None:
        """Enable embedded mode with direct dict references (no HTTP for prices/positions)."""
        self._direct_mark_prices = mark_prices
        self._direct_positions = positions

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.cfg.request_timeout_seconds)
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def run_forever(self) -> None:
        try:
            while True:
                try:
                    stats = await self.run_once()
                    logger.info(
                        "bridge cycle scanned=%s generated=%s submitted=%s "
                        "no_price=%s cooldown=%s held=%s guard_blocked=%s",
                        stats.scanned_cards,
                        stats.generated_signals,
                        stats.submitted_signals,
                        stats.skipped_no_price,
                        stats.skipped_cooldown,
                        stats.skipped_already_held,
                        stats.skipped_guard_blocked,
                    )
                except Exception as exc:
                    logger.exception("bridge cycle failed err=%s", exc)
                await asyncio.sleep(self.cfg.poll_interval_seconds)
        finally:
            await self.close()

    async def run_once(self) -> BridgeStats:
        stats = BridgeStats()
        client = await self._get_client()

        cards = await self._fetch_cards(client)
        stats.scanned_cards = len(cards)

        now_ts = time.time()

        # Fetch currently held positions to pre-filter
        held_symbols = await self._fetch_positions(client)

        drafts: list[SignalDraft] = []
        for card in cards:
            draft = card_to_signal(card, self.cfg)
            if draft is None:
                continue
            if not self.cooldown.allowed(
                draft.symbol,
                draft.side,
                cooldown_seconds=self.cfg.cooldown_seconds,
                now_ts=now_ts,
            ):
                stats.skipped_cooldown += 1
                continue
            # Skip BUY if already holding (executor would reject as ALREADY_LONG anyway)
            if draft.side == "BUY" and draft.symbol in held_symbols:
                stats.skipped_already_held += 1
                continue
            # Skip SELL if not holding (executor would reject as NO_LONG_TO_EXIT)
            if draft.side == "SELL" and draft.symbol not in held_symbols:
                continue
            drafts.append(draft)

        stats.generated_signals = len(drafts)
        if not drafts:
            return stats

        # Fetch CompoundingGuard for each unique ticker and apply
        if self.cfg.guard_enabled:
            drafts = await self._apply_guards(client, drafts, stats)

        if not drafts:
            return stats

        price_map = await self._fetch_prices(client, sorted({d.symbol for d in drafts}))
        for draft in drafts:
            price = price_map.get(draft.symbol)
            if price is None or price <= 0:
                stats.skipped_no_price += 1
                logger.warning("skip signal missing price symbol=%s", draft.symbol)
                continue
            ok = await self._submit_signal(client, draft, price)
            if ok:
                self.cooldown.mark(draft.symbol, draft.side, now_ts=now_ts)
                stats.submitted_signals += 1
        return stats

    async def _apply_guards(
        self,
        client: httpx.AsyncClient,
        drafts: list[SignalDraft],
        stats: BridgeStats,
    ) -> list[SignalDraft]:
        """Fetch CompoundingGuard for each ticker and apply multiplier to confidence."""
        unique_tickers = sorted({d.symbol for d in drafts})
        guards: dict[str, dict[str, Any]] = {}
        for ticker in unique_tickers:
            guard = await self._fetch_guard(client, ticker)
            if guard is not None:
                guards[ticker] = guard

        filtered: list[SignalDraft] = []
        for draft in drafts:
            guard = guards.get(draft.symbol)
            if guard:
                multiplier = _as_float(guard.get("position_multiplier"), 1.0)
                risk_ok = bool(guard.get("risk_ok", True))
                horizon = str(guard.get("hold_horizon_hint", "1d"))

                draft.guard_multiplier = multiplier
                draft.guard_risk_ok = risk_ok
                draft.hold_horizon_hint = horizon

                # Modulate confidence: base_confidence * guard_multiplier
                draft.confidence = _clamp(draft.confidence * multiplier, 0.05, 1.0)

                # Block BUY if guard multiplier too low or risk not OK
                if draft.side == "BUY":
                    if multiplier < self.cfg.min_guard_multiplier_for_buy:
                        logger.info(
                            "skip buy guard_multiplier_too_low symbol=%s mult=%.2f",
                            draft.symbol, multiplier,
                        )
                        stats.skipped_guard_blocked += 1
                        continue
                    if not risk_ok:
                        logger.info(
                            "skip buy guard_risk_not_ok symbol=%s reasons=%s",
                            draft.symbol, guard.get("reasons", []),
                        )
                        stats.skipped_guard_blocked += 1
                        continue

            filtered.append(draft)
        return filtered

    async def _fetch_guard(
        self,
        client: httpx.AsyncClient,
        ticker: str,
    ) -> dict[str, Any] | None:
        """Fetch CompoundingGuard from AIStock sentiment engine GET /guard/{ticker}."""
        url = f"{self.cfg.sentiment_engine_base_url}/guard/{ticker}"
        try:
            resp = await client.get(url, timeout=httpx.Timeout(self.cfg.guard_timeout_seconds))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("guard fetch failed ticker=%s err=%s", ticker, exc)
            return None

    async def _fetch_cards(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        url = f"{self.cfg.aistock_base_url}/dashboard"
        resp = await client.get(
            url,
            params={"sort_by": "priority", "limit": self.cfg.dashboard_limit},
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            logger.warning("unexpected dashboard payload type=%s", type(payload).__name__)
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def _fetch_positions(self, client: httpx.AsyncClient) -> set[str]:
        """Fetch currently held positions from executor (or direct state)."""
        if self._direct_positions is not None:
            return {sym for sym, qty in self._direct_positions.items() if qty > 0}
        try:
            url = f"{self.cfg.executor_base_url}/positions"
            headers: dict[str, str] = {}
            if self.cfg.executor_api_key:
                headers["X-API-Key"] = self.cfg.executor_api_key
            resp = await client.get(url, headers=headers, timeout=httpx.Timeout(3.0))
            if resp.status_code == 200:
                data = resp.json()
                positions = data.get("positions", {})
                return {sym for sym, qty in positions.items() if int(qty) > 0}
        except Exception as exc:
            logger.debug("positions fetch failed err=%s", exc)
        return set()

    async def _fetch_prices(
        self,
        client: httpx.AsyncClient,
        symbols: list[str],
    ) -> dict[str, float]:
        if not symbols:
            return {}

        out: dict[str, float] = {}

        # Tier 1: Direct state (embedded mode)
        if self._direct_mark_prices is not None:
            for sym in symbols:
                price = self._direct_mark_prices.get(sym)
                if price and price > 0:
                    out[sym] = price

        # Tier 2: Executor mark prices via HTTP (if not embedded)
        if self._direct_mark_prices is None:
            try:
                url = f"{self.cfg.executor_base_url}/marks"
                headers: dict[str, str] = {}
                if self.cfg.executor_api_key:
                    headers["X-API-Key"] = self.cfg.executor_api_key
                resp = await client.get(url, headers=headers, timeout=httpx.Timeout(3.0))
                if resp.status_code == 200:
                    data = resp.json()
                    marks = data.get("marks", {})
                    for sym in symbols:
                        if sym not in out:
                            price = _as_float(marks.get(sym))
                            if price > 0:
                                out[sym] = price
            except Exception as exc:
                logger.debug("mark prices fetch failed err=%s", exc)

        # Tier 3: Yahoo Finance fallback for missing symbols
        missing = [s for s in symbols if s not in out]
        if missing:
            yahoo_prices = await self._fetch_yahoo_prices(client, missing)
            out.update(yahoo_prices)

        return out

    async def _fetch_yahoo_prices(
        self,
        client: httpx.AsyncClient,
        symbols: list[str],
    ) -> dict[str, float]:
        """Fallback price source via Yahoo Finance."""
        if not symbols:
            return {}
        try:
            url = "https://query1.finance.yahoo.com/v7/finance/quote"
            resp = await client.get(url, params={"symbols": ",".join(symbols)})
            resp.raise_for_status()
            payload = resp.json()
            result = (
                payload.get("quoteResponse", {}).get("result", [])
                if isinstance(payload, dict)
                else []
            )
            out: dict[str, float] = {}
            for item in result:
                if not isinstance(item, dict):
                    continue
                symbol = _normalize_symbol(item.get("symbol"))
                price = _as_float(item.get("regularMarketPrice"), default=0.0)
                if symbol and price > 0:
                    out[symbol] = price
            return out
        except Exception as exc:
            logger.warning("yahoo price fetch failed err=%s", exc)
            return {}

    async def _submit_signal(
        self,
        client: httpx.AsyncClient,
        draft: SignalDraft,
        price: float,
    ) -> bool:
        payload: dict[str, Any] = {
            "symbol": draft.symbol,
            "side": draft.side,
            "confidence": round(draft.confidence, 4),
            "reason": draft.reason,
            "price": round(price, 4),
            "meta": {
                "guard_multiplier": round(draft.guard_multiplier, 4),
                "guard_risk_ok": draft.guard_risk_ok,
                "hold_horizon_hint": draft.hold_horizon_hint,
                "source_priority": round(draft.priority_score, 2),
                "source_sentiment": round(draft.sentiment, 4),
                "source_momentum": round(draft.momentum, 4),
            },
        }
        headers: dict[str, str] = {}
        if self.cfg.executor_api_key:
            headers["X-API-Key"] = self.cfg.executor_api_key

        if self.cfg.dry_run:
            logger.info("dry-run signal payload=%s", payload)
            return True

        url = f"{self.cfg.executor_base_url}/signals"
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "signal submit failed status=%s symbol=%s side=%s body=%s",
                resp.status_code,
                draft.symbol,
                draft.side,
                resp.text,
            )
            return False

        data = resp.json()
        accepted = bool(data.get("accepted"))
        if accepted:
            logger.info(
                "signal submitted symbol=%s side=%s confidence=%.3f guard_mult=%.2f queue_size=%s",
                draft.symbol,
                draft.side,
                draft.confidence,
                draft.guard_multiplier,
                data.get("queue_size"),
            )
        else:
            logger.warning(
                "signal not accepted symbol=%s side=%s body=%s",
                draft.symbol,
                draft.side,
                data,
            )
        return accepted
