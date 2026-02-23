from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from src.common.models import HealthSnapshot, Signal
from src.control.server import ExecutionControlServer
from src.data.store import SQLiteStore
from src.execution.executor import ExecutionEngine
from src.execution.ibkr_client import IBKRClient
from src.logging_conf import configure_logging
from src.monitoring.health import HealthTracker
from src.monitoring.notifier import Notifier
from src.risk.kill_switch import KillSwitch
from src.risk.rules import RiskEngine
from src.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class ExecutionApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stop_event = asyncio.Event()

        self.signal_queue: asyncio.Queue[Signal] = asyncio.Queue(
            maxsize=settings.signal_queue_size
        )

        self.store = SQLiteStore(settings.database_url)
        self.notifier = Notifier(
            telegram_bot_token=settings.telegram_bot_token,
            telegram_chat_id=settings.telegram_chat_id,
        )
        self.kill_switch = KillSwitch(
            initial_state=settings.kill_switch,
            kill_file=settings.kill_switch_file,
        )
        self.risk = RiskEngine(
            max_positions=settings.max_positions,
            max_daily_loss_usd=settings.max_daily_loss_usd,
            max_order_notional_usd=settings.max_order_notional_usd,
            max_total_notional_usd=settings.max_total_notional_usd,
        )
        self.ibkr = IBKRClient(
            host=settings.ibkr_host,
            port=settings.ibkr_port,
            client_id=settings.ibkr_client_id,
            account=settings.ibkr_account,
        )
        self.executor = ExecutionEngine(
            ibkr=self.ibkr,
            risk=self.risk,
            store=self.store,
            notifier=self.notifier,
            kill_switch=self.kill_switch,
            stop_loss_pct=settings.stop_loss_pct,
            take_profit_pct=settings.take_profit_pct,
        )
        self.health_tracker = HealthTracker(
            HealthSnapshot(
                trading_mode=settings.trading_mode,
                app_env=settings.app_env,
                kill_switch=settings.kill_switch,
            )
        )
        self.control_server = ExecutionControlServer(
            tracker=self.health_tracker,
            kill_switch=self.kill_switch,
            enqueue_signal=self.enqueue_signal,
            update_mark=self.executor.update_mark,
            host=settings.control_host,
            port=settings.control_port,
            api_key=settings.control_api_key,
        )
        self._last_ibkr_connected: bool | None = None

    async def enqueue_signal(self, signal: Signal) -> int:
        self.signal_queue.put_nowait(signal)
        return self.signal_queue.qsize()

    async def run(self) -> None:
        await self.notifier.send(
            f"Execution app boot env={self.settings.app_env} mode={self.settings.trading_mode}"
        )
        await self.health_tracker.update(
            control_server_ready=True,
            kill_switch=self.kill_switch.is_active(),
        )

        connected = await self.ibkr.connect(max_retries=3)
        await self.health_tracker.update(ibkr_connected=connected)
        if connected:
            await self.notifier.send("IBKR CONNECTED")

        tasks = [
            asyncio.create_task(self._guarded("signal_worker", self._signal_worker())),
            asyncio.create_task(self._guarded("broker_sync", self._broker_sync_loop())),
            asyncio.create_task(self._guarded("health_update", self._health_update_loop())),
            asyncio.create_task(self._guarded("control_http", self.control_server.serve())),
        ]

        try:
            await self.stop_event.wait()
        finally:
            logger.info("shutdown started")
            await self.control_server.shutdown()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.ibkr.disconnect()
            self.store.close()
            await self.notifier.send("Execution app stopped")

    async def _guarded(self, name: str, coro: Awaitable[None]) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("task crashed name=%s err=%s", name, exc)
            self.stop_event.set()

    async def _signal_worker(self) -> None:
        while not self.stop_event.is_set():
            signal = await self.signal_queue.get()
            self.store.insert_signal(signal)
            logger.info(
                "signal id=%s symbol=%s side=%s confidence=%.4f reason=%s",
                signal.id,
                signal.symbol,
                signal.side.value,
                signal.confidence,
                signal.reason,
            )
            await self.executor.process_signal(signal)
            await self.health_tracker.update(
                signal_queue_size=self.signal_queue.qsize(),
                last_signal_ts_ms=signal.ts_ms,
            )

    async def _broker_sync_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.executor.refresh_broker_state()
                await self.health_tracker.update(ibkr_connected=self.ibkr.connected)
            except Exception as exc:
                logger.warning("broker sync failed err=%s", exc)
            await asyncio.sleep(15)

    async def _health_update_loop(self) -> None:
        while not self.stop_event.is_set():
            ibkr_connected = self.ibkr.connected

            if self._last_ibkr_connected is None or ibkr_connected != self._last_ibkr_connected:
                state = "CONNECTED" if ibkr_connected else "DISCONNECTED"
                await self.notifier.send(f"IBKR {state}")
                self._last_ibkr_connected = ibkr_connected

            await self.health_tracker.update(
                control_server_ready=True,
                ibkr_connected=ibkr_connected,
                signal_queue_size=self.signal_queue.qsize(),
                kill_switch=self.kill_switch.is_active(),
            )
            await asyncio.sleep(1)


def main() -> None:
    settings = get_settings()
    log_dir = configure_logging(
        log_level=settings.log_level,
        log_dir=settings.log_dir,
        retention_days=settings.log_retention_days,
    )
    logger.info(
        "starting execution app env=%s mode=%s control_host=%s control_port=%s log_dir=%s",
        settings.app_env,
        settings.trading_mode,
        settings.control_host,
        settings.control_port,
        str(log_dir),
    )
    app = ExecutionApp(settings)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("keyboard interrupt received")


if __name__ == "__main__":
    main()
