from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.ids import new_signal_id
from src.common.models import Side, Signal
from src.common.timeutil import now_utc_ms
from src.data.store import SQLiteStore
from src.execution.executor import ExecutionEngine
from src.execution.ibkr_client import IBKRClient
from src.logging_conf import configure_logging
from src.monitoring.notifier import Notifier
from src.risk.kill_switch import KillSwitch
from src.risk.rules import RiskEngine
from src.settings import get_settings

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit one test signal through ExecutionEngine to validate IBKR order flow."
    )
    parser.add_argument("--symbol", required=True, help="Ticker symbol, e.g. AAPL")
    parser.add_argument(
        "--side",
        choices=["buy", "sell"],
        default="buy",
        help="Signal side",
    )
    parser.add_argument(
        "--price",
        required=True,
        type=float,
        help="Reference price used for risk sizing and bracket TP/SL",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=1.0,
        help="Signal confidence",
    )
    parser.add_argument(
        "--reason",
        default="MANUAL_TEST_ORDER",
        help="Signal reason text",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=None,
        help="Override IBKR client id. Defaults to IBKR_CLIENT_ID + 100.",
    )
    parser.add_argument(
        "--ignore-kill-switch",
        action="store_true",
        help="Ignore env/file kill switch for this manual test process.",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Allow running when TRADING_MODE=live (blocked by default).",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    if settings.trading_mode != "paper" and not args.allow_live:
        logger.error(
            "blocked: TRADING_MODE=%s. pass --allow-live to override intentionally.",
            settings.trading_mode,
        )
        return 2

    symbol = args.symbol.strip().upper()
    side = Side.BUY if args.side == "buy" else Side.SELL
    price = float(args.price)
    if price <= 0:
        logger.error("invalid --price: must be > 0")
        return 2

    client_id = args.client_id if args.client_id is not None else settings.ibkr_client_id + 100
    kill_file = "./__MANUAL_TEST_KILL_FILE_UNUSED__" if args.ignore_kill_switch else settings.kill_switch_file
    kill_initial = False if args.ignore_kill_switch else settings.kill_switch

    store = SQLiteStore(settings.database_url)
    notifier = Notifier(settings.telegram_bot_token, settings.telegram_chat_id)
    kill_switch = KillSwitch(initial_state=kill_initial, kill_file=kill_file)
    risk = RiskEngine(
        max_positions=settings.max_positions,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        max_order_notional_usd=settings.max_order_notional_usd,
        max_total_notional_usd=settings.max_total_notional_usd,
    )
    ibkr = IBKRClient(
        host=settings.ibkr_host,
        port=settings.ibkr_port,
        client_id=client_id,
        account=settings.ibkr_account,
    )
    executor = ExecutionEngine(
        ibkr=ibkr,
        risk=risk,
        store=store,
        notifier=notifier,
        kill_switch=kill_switch,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
    )

    signal = Signal(
        id=new_signal_id(symbol),
        symbol=symbol,
        side=side,
        confidence=max(0.0, min(1.0, float(args.confidence))),
        reason=args.reason,
        ts_ms=now_utc_ms(),
    )

    try:
        ok = await ibkr.connect(max_retries=3)
        if not ok:
            logger.error("ibkr connection failed")
            return 3

        await executor.refresh_broker_state()
        executor.update_mark(symbol, price)
        await executor.process_signal(signal)

        with store.lock:
            row = store.conn.execute(
                """
                SELECT status, reason, broker_order_id, qty
                FROM orders
                WHERE signal_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (signal.id,),
            ).fetchone()

        if not row:
            logger.error("no order record found for signal_id=%s", signal.id)
            return 4

        status, reason, broker_order_id, qty = row
        logger.info(
            "test_order_result signal_id=%s status=%s reason=%s broker_order_id=%s qty=%s",
            signal.id,
            status,
            reason,
            broker_order_id,
            qty,
        )

        if status == "SUBMITTED":
            return 0
        return 5
    finally:
        await ibkr.disconnect()
        store.close()


def main() -> None:
    code = asyncio.run(run())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
