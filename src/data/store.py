from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from src.common.models import Bar, FillEvent, OrderEvent, Signal


class SQLiteStore:
    def __init__(self, database_url: str) -> None:
        self.db_path = self._parse_sqlite_path(database_url)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self._ensure_schema()

    @staticmethod
    def _parse_sqlite_path(database_url: str) -> Path:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("only sqlite:/// urls are supported for MVP")
        return Path(database_url[len(prefix) :]).resolve()

    def _ensure_schema(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    start_ts_ms INTEGER NOT NULL,
                    end_ts_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    broker_order_id INTEGER,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_order_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    avg_price REAL NOT NULL,
                    ts_ms INTEGER NOT NULL
                );
                """
            )

    def insert_bar(self, bar: Bar) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO bars(symbol, open, high, low, close, volume, start_ts_ms, end_ts_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bar.symbol,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.start_ts_ms,
                    bar.end_ts_ms,
                ),
            )

    def insert_signal(self, signal: Signal) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO signals(id, symbol, side, confidence, reason, ts_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.id,
                    signal.symbol,
                    signal.side.value,
                    signal.confidence,
                    signal.reason,
                    signal.ts_ms,
                ),
            )

    def insert_order(self, event: OrderEvent) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO orders(signal_id, symbol, side, qty, broker_order_id, status, reason, ts_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.signal_id,
                    event.symbol,
                    event.side.value,
                    event.qty,
                    event.order_id,
                    event.status,
                    event.reason,
                    event.ts_ms,
                ),
            )

    def insert_fill(self, event: FillEvent) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO fills(broker_order_id, symbol, side, qty, avg_price, ts_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.order_id,
                    event.symbol,
                    event.side.value,
                    event.qty,
                    event.avg_price,
                    event.ts_ms,
                ),
            )

    def close(self) -> None:
        with self.lock:
            self.conn.close()
