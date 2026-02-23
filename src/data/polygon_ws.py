from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

import websockets

from src.common.models import Bar, Tick
from src.common.retry import RetryPolicy

logger = logging.getLogger(__name__)


class PolygonWSClient:
    def __init__(
        self,
        ws_url: str,
        api_key: str,
        symbols: list[str],
        feed: Literal["trades", "am"],
        tick_queue: asyncio.Queue[Tick] | None = None,
        bar_queue: asyncio.Queue[Bar] | None = None,
        max_retries: int = 20,
        heartbeat_seconds: int = 20,
    ) -> None:
        self.ws_url = ws_url
        self.api_key = api_key
        self.symbols = symbols
        self.feed = feed
        self.tick_queue = tick_queue
        self.bar_queue = bar_queue
        self.heartbeat_seconds = heartbeat_seconds
        self.retry_policy = RetryPolicy(max_retries=max_retries)
        self.connected = False

        if self.feed == "trades" and self.tick_queue is None:
            raise ValueError("tick_queue is required when feed='trades'")
        if self.feed == "am" and self.bar_queue is None:
            raise ValueError("bar_queue is required when feed='am'")

    async def start(self, stop_event: asyncio.Event) -> None:
        attempt = 0
        while not stop_event.is_set():
            try:
                await self._run_session(stop_event)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                attempt += 1
                logger.exception("polygon stream error attempt=%s err=%s", attempt, exc)
                if attempt > self.retry_policy.max_retries:
                    logger.error("polygon max retries exceeded, stopping stream loop")
                    return
                await self.retry_policy.sleep_for_attempt(
                    attempt,
                    on_sleep=lambda n, d: logger.warning(
                        "polygon reconnect retry=%s sleep=%.1fs", n, d
                    ),
                )

    async def _run_session(self, stop_event: asyncio.Event) -> None:
        if not self.api_key:
            raise RuntimeError("POLYGON_API_KEY is empty")
        if not self.symbols:
            raise RuntimeError("no symbols configured")

        logger.info("connecting polygon ws url=%s", self.ws_url)
        async with websockets.connect(
            self.ws_url,
            ping_interval=None,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
        ) as ws:
            await self._authenticate(ws)
            await self._subscribe(ws)
            self.connected = True
            logger.info("polygon connected feed=%s symbols=%s", self.feed, ",".join(self.symbols))

            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=float(self.heartbeat_seconds)
                    )
                except asyncio.TimeoutError:
                    await self._heartbeat(ws)
                    continue
                await self._handle_raw_message(raw)

            self.connected = False

    async def _authenticate(self, ws: websockets.ClientConnection) -> None:
        await ws.send(json.dumps({"action": "auth", "params": self.api_key}))

    async def _subscribe(self, ws: websockets.ClientConnection) -> None:
        prefix = "T" if self.feed == "trades" else "AM"
        channels = ",".join(f"{prefix}.{symbol}" for symbol in self.symbols)
        await ws.send(json.dumps({"action": "subscribe", "params": channels}))

    async def _heartbeat(self, ws: websockets.ClientConnection) -> None:
        pong_waiter = await ws.ping()
        await asyncio.wait_for(pong_waiter, timeout=5.0)
        logger.debug("polygon heartbeat ok")

    async def _handle_raw_message(self, raw: str | bytes) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("polygon message parse failed raw=%s", raw)
            return

        messages: list[dict[str, Any]]
        if isinstance(payload, list):
            messages = [m for m in payload if isinstance(m, dict)]
        elif isinstance(payload, dict):
            messages = [payload]
        else:
            return

        for msg in messages:
            await self._handle_message(msg)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        ev = str(msg.get("ev", msg.get("event", ""))).strip()
        if ev.lower() == "status":
            status = msg.get("status", "")
            logger.info("polygon status status=%s msg=%s", status, msg.get("message", ""))
            return
        if ev == "T":
            await self._handle_trade_message(msg)
            return
        if ev == "AM":
            await self._handle_minute_aggregate_message(msg)
            return

    async def _handle_trade_message(self, msg: dict[str, Any]) -> None:
        symbol = str(msg.get("sym", "")).upper().strip()
        if not symbol:
            return

        price_raw = msg.get("p")
        size_raw = msg.get("s", 0)
        ts_raw = msg.get("t", 0)
        try:
            price = float(price_raw)
            size = float(size_raw)
            ts_ms = self._normalize_timestamp(ts_raw)
        except (TypeError, ValueError):
            logger.warning("invalid trade payload ignored msg=%s", msg)
            return

        tick = Tick(symbol=symbol, price=price, size=size, ts_ms=ts_ms)
        if self.tick_queue is not None:
            await self.tick_queue.put(tick)

    async def _handle_minute_aggregate_message(self, msg: dict[str, Any]) -> None:
        symbol = str(msg.get("sym", "")).upper().strip()
        if not symbol:
            return

        try:
            open_px = float(msg.get("o"))
            high_px = float(msg.get("h"))
            low_px = float(msg.get("l"))
            close_px = float(msg.get("c"))
            volume = float(msg.get("v", 0))
            start_ts_ms = self._normalize_timestamp(msg.get("s", 0))
            end_ts_ms = self._normalize_timestamp(msg.get("e", start_ts_ms + 59_999))
        except (TypeError, ValueError):
            logger.warning("invalid minute aggregate payload ignored msg=%s", msg)
            return

        if end_ts_ms < start_ts_ms:
            end_ts_ms = start_ts_ms + 59_999

        bar = Bar(
            symbol=symbol,
            open=open_px,
            high=high_px,
            low=low_px,
            close=close_px,
            volume=volume,
            start_ts_ms=start_ts_ms,
            end_ts_ms=end_ts_ms,
        )
        if self.bar_queue is not None:
            await self.bar_queue.put(bar)

    @staticmethod
    def _normalize_timestamp(ts_value: Any) -> int:
        ts = int(ts_value)
        # Polygon may emit ns/us/ms timestamps depending on feed type.
        if ts > 10_000_000_000_000_000:
            return ts // 1_000_000
        if ts > 10_000_000_000_000:
            return ts // 1_000
        return ts
