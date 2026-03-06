from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.logging_conf import configure_logging
from src.integrations.aistock_bridge import AIStockBridge, BridgeConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge AIStock decision cards to this executor /signals endpoint."
    )
    parser.add_argument("--aistock-url", default=os.getenv("AISTOCK_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--sentiment-url", default=os.getenv("AISTOCK_SENTIMENT_URL", "http://127.0.0.1:8002"))
    parser.add_argument("--executor-url", default=os.getenv("EXECUTOR_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--executor-api-key", default=os.getenv("EXECUTOR_API_KEY", ""))
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("AISTOCK_BRIDGE_INTERVAL", "20")),
        help="Polling interval seconds",
    )
    parser.add_argument(
        "--dashboard-limit",
        type=int,
        default=int(os.getenv("AISTOCK_DASHBOARD_LIMIT", "30")),
    )
    parser.add_argument(
        "--min-priority-buy",
        type=float,
        default=float(os.getenv("AISTOCK_MIN_PRIORITY_BUY", "55.0")),
    )
    parser.add_argument(
        "--min-sentiment-buy",
        type=float,
        default=float(os.getenv("AISTOCK_MIN_SENTIMENT_BUY", "0.2")),
    )
    parser.add_argument(
        "--min-momentum-buy",
        type=float,
        default=float(os.getenv("AISTOCK_MIN_MOMENTUM_BUY", "0.05")),
    )
    parser.add_argument(
        "--max-crowding-buy",
        type=float,
        default=float(os.getenv("AISTOCK_MAX_CROWDING_BUY", "0.75")),
    )
    parser.add_argument(
        "--max-sentiment-sell",
        type=float,
        default=float(os.getenv("AISTOCK_MAX_SENTIMENT_SELL", "-0.15")),
    )
    parser.add_argument(
        "--max-momentum-sell",
        type=float,
        default=float(os.getenv("AISTOCK_MAX_MOMENTUM_SELL", "-0.10")),
    )
    parser.add_argument(
        "--min-risk-penalty-sell",
        type=float,
        default=float(os.getenv("AISTOCK_MIN_RISK_PENALTY_SELL", "12.0")),
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=int(os.getenv("AISTOCK_COOLDOWN_SECONDS", "180")),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("AISTOCK_BRIDGE_TIMEOUT_SECONDS", "10.0")),
    )
    parser.add_argument("--no-guard", action="store_true", help="Disable CompoundingGuard fetch")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not call executor /signals")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args()


async def _run() -> int:
    args = parse_args()
    configure_logging(args.log_level)

    cfg = BridgeConfig(
        aistock_base_url=args.aistock_url,
        sentiment_engine_base_url=args.sentiment_url,
        executor_base_url=args.executor_url,
        executor_api_key=args.executor_api_key,
        request_timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.interval,
        dashboard_limit=args.dashboard_limit,
        min_priority_for_buy=args.min_priority_buy,
        min_sentiment_for_buy=args.min_sentiment_buy,
        min_momentum_for_buy=args.min_momentum_buy,
        max_crowding_for_buy=args.max_crowding_buy,
        max_sentiment_for_sell=args.max_sentiment_sell,
        max_momentum_for_sell=args.max_momentum_sell,
        min_neg_risk_penalty_for_sell=args.min_risk_penalty_sell,
        cooldown_seconds=args.cooldown_seconds,
        guard_enabled=not args.no_guard,
        dry_run=args.dry_run,
    )
    bridge = AIStockBridge(cfg)

    if args.once:
        stats = await bridge.run_once()
        logging.getLogger(__name__).info(
            "bridge once scanned=%s generated=%s submitted=%s "
            "no_price=%s cooldown=%s held=%s guard_blocked=%s",
            stats.scanned_cards,
            stats.generated_signals,
            stats.submitted_signals,
            stats.skipped_no_price,
            stats.skipped_cooldown,
            stats.skipped_already_held,
            stats.skipped_guard_blocked,
        )
        await bridge.close()
        return 0

    await bridge.run_forever()
    return 0


def main() -> None:
    code = asyncio.run(_run())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
