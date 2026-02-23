from __future__ import annotations

import math


def fixed_notional_quantity(price: float, max_notional_usd: float) -> int:
    if price <= 0 or max_notional_usd <= 0:
        return 0
    return max(0, math.floor(max_notional_usd / price))
