from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.common.ids import new_signal_id
from src.common.models import Side, Signal
from src.common.timeutil import now_utc_ms
from src.monitoring.health import HealthTracker
from src.risk.kill_switch import KillSwitch


class SignalIn(BaseModel):
    signal_id: str | None = None
    symbol: str
    side: Literal["BUY", "SELL", "buy", "sell"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = "EXTERNAL_SIGNAL"
    ts_ms: int | None = None
    price: float | None = Field(default=None, gt=0.0)
    meta: dict[str, Any] | None = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        out = value.strip().upper()
        if not out:
            raise ValueError("symbol must not be empty")
        return out

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        out = value.strip()
        if not out:
            raise ValueError("reason must not be empty")
        return out

    def to_signal(self) -> Signal:
        side = Side.BUY if self.side.upper() == "BUY" else Side.SELL
        return Signal(
            id=self.signal_id or new_signal_id(self.symbol),
            symbol=self.symbol,
            side=side,
            confidence=float(self.confidence),
            reason=self.reason,
            ts_ms=self.ts_ms or now_utc_ms(),
            meta=self.meta or {},
        )


class MarkIn(BaseModel):
    symbol: str
    price: float = Field(gt=0.0)

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        out = value.strip().upper()
        if not out:
            raise ValueError("symbol must not be empty")
        return out


class ExecutionControlServer:
    def __init__(
        self,
        tracker: HealthTracker,
        kill_switch: KillSwitch,
        enqueue_signal: Callable[[Signal], Awaitable[int]],
        update_mark: Callable[[str, float], None],
        get_mark_prices: Callable[[], dict[str, float]],
        get_positions: Callable[[], dict[str, int]],
        host: str,
        port: int,
        api_key: str = "",
    ) -> None:
        self.tracker = tracker
        self.kill_switch = kill_switch
        self.enqueue_signal = enqueue_signal
        self.update_mark = update_mark
        self.get_mark_prices = get_mark_prices
        self.get_positions = get_positions
        self.host = host
        self.port = port
        self.api_key = api_key

        self.app = FastAPI(title="Trade Execution Control API")
        self._server: uvicorn.Server | None = None
        self._mount_routes()

    def _require_api_key(self, x_api_key: str | None) -> None:
        if self.api_key and x_api_key != self.api_key:
            raise HTTPException(status_code=401, detail="invalid api key")

    def _mount_routes(self) -> None:
        @self.app.get("/health")
        async def health() -> dict[str, object]:
            snapshot = await self.tracker.get_snapshot()
            snapshot["kill_switch"] = self.kill_switch.is_active()
            return snapshot

        @self.app.post("/kill")
        async def kill(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, object]:
            self._require_api_key(x_api_key)
            self.kill_switch.trigger()
            await self.tracker.update(kill_switch=True)
            return {"ok": True, "kill_switch": True}

        @self.app.post("/marks")
        async def marks(
            payload: MarkIn,
            x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        ) -> dict[str, object]:
            self._require_api_key(x_api_key)
            self.update_mark(payload.symbol, float(payload.price))
            return {"ok": True, "symbol": payload.symbol, "price": float(payload.price)}

        @self.app.get("/marks")
        async def get_marks() -> dict[str, object]:
            return {"marks": self.get_mark_prices()}

        @self.app.get("/positions")
        async def get_positions() -> dict[str, object]:
            return {"positions": self.get_positions()}

        @self.app.post("/signals")
        async def signals(
            payload: SignalIn,
            x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        ) -> dict[str, object]:
            self._require_api_key(x_api_key)

            if payload.price is not None:
                self.update_mark(payload.symbol, float(payload.price))

            signal = payload.to_signal()
            try:
                queue_size = await self.enqueue_signal(signal)
            except asyncio.QueueFull as exc:
                raise HTTPException(status_code=429, detail="signal queue is full") from exc

            await self.tracker.update(
                signal_queue_size=queue_size,
                last_signal_ts_ms=signal.ts_ms,
            )
            return {
                "accepted": True,
                "signal_id": signal.id,
                "symbol": signal.symbol,
                "side": signal.side.value,
                "queue_size": queue_size,
            }

    async def serve(self) -> None:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        await self._server.serve()

    async def shutdown(self) -> None:
        if self._server:
            self._server.should_exit = True

