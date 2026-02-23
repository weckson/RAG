from __future__ import annotations

import sqlite3
from pathlib import Path

from src.common.models import Bar


def load_bars_from_sqlite(db_path: str, symbol: str) -> list[Bar]:
    conn = sqlite3.connect(Path(db_path))
    rows = conn.execute(
        """
        SELECT symbol, open, high, low, close, volume, start_ts_ms, end_ts_ms
        FROM bars
        WHERE symbol = ?
        ORDER BY start_ts_ms ASC
        """,
        (symbol,),
    ).fetchall()
    conn.close()
    return [
        Bar(
            symbol=row[0],
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            start_ts_ms=row[6],
            end_ts_ms=row[7],
        )
        for row in rows
    ]
