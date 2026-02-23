from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ib_insync import IB, Contract, Order, Stock, Trade

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PositionSnapshot:
    symbol: str
    qty: int
    avg_cost: float


class IBKRClient:
    def __init__(self, host: str, port: int, client_id: int, account: str = "") -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account = account
        self.ib = IB()
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return bool(self.ib.isConnected())

    async def connect(self, max_retries: int = 5) -> bool:
        if self.connected:
            return True
        for attempt in range(1, max_retries + 1):
            try:
                await self.ib.connectAsync(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id,
                    timeout=10,
                    readonly=False,
                    account=self.account or "",
                )
                logger.info(
                    "ibkr connected host=%s port=%s client_id=%s",
                    self.host,
                    self.port,
                    self.client_id,
                )
                return True
            except Exception as exc:
                delay = min(2**attempt, 30)
                logger.warning(
                    "ibkr connect failed attempt=%s err=%s retry_in=%ss",
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        return False

    async def ensure_connected(self) -> bool:
        return self.connected or await self.connect()

    async def disconnect(self) -> None:
        if self.connected:
            self.ib.disconnect()
            logger.info("ibkr disconnected")

    async def next_order_id(self) -> int:
        async with self._lock:
            await self.ensure_connected()
            return self.ib.client.getReqId()

    async def _qualify_stock(self, symbol: str) -> Contract:
        contract = Stock(symbol, "SMART", "USD")
        contracts = await self.ib.qualifyContractsAsync(contract)
        if not contracts:
            raise RuntimeError(f"failed to qualify contract for {symbol}")
        return contracts[0]

    async def place_orders(self, symbol: str, orders: list[Order]) -> list[Trade]:
        async with self._lock:
            if not await self.ensure_connected():
                raise RuntimeError("IBKR not connected")
            contract = await self._qualify_stock(symbol)
            trades: list[Trade] = []
            for order in orders:
                trade = self.ib.placeOrder(contract, order)
                trades.append(trade)
            return trades

    async def get_positions(self) -> dict[str, PositionSnapshot]:
        async with self._lock:
            if not await self.ensure_connected():
                return {}
            positions = await self.ib.reqPositionsAsync()
        out: dict[str, PositionSnapshot] = {}
        for pos in positions:
            if self.account and pos.account != self.account:
                continue
            symbol = pos.contract.symbol
            out[symbol] = PositionSnapshot(
                symbol=symbol,
                qty=int(pos.position),
                avg_cost=float(pos.avgCost),
            )
        return out

    async def get_account_values(self) -> dict[str, float]:
        async with self._lock:
            if not await self.ensure_connected():
                return {}
            summary = await self.ib.accountSummaryAsync(self.account or "")
        out: dict[str, float] = {}
        for item in summary:
            if item.value in ("", None):
                continue
            try:
                out[item.tag] = float(item.value)
            except ValueError:
                continue
        return out
