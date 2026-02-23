from __future__ import annotations

from dataclasses import dataclass, field

from src.execution.ibkr_client import PositionSnapshot


@dataclass(slots=True)
class BrokerState:
    positions: dict[str, int] = field(default_factory=dict)
    avg_costs: dict[str, float] = field(default_factory=dict)
    open_order_ids: set[int] = field(default_factory=set)

    def update_positions(self, snapshots: dict[str, PositionSnapshot]) -> None:
        self.positions = {symbol: snapshot.qty for symbol, snapshot in snapshots.items()}
        self.avg_costs = {symbol: snapshot.avg_cost for symbol, snapshot in snapshots.items()}

    def position_qty(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)
