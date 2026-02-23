from __future__ import annotations

import uuid


def new_signal_id(symbol: str) -> str:
    return f"sig_{symbol}_{uuid.uuid4().hex[:12]}"
