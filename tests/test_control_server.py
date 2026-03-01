from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from src.common.models import HealthSnapshot, Signal
from src.control.server import ExecutionControlServer
from src.monitoring.health import HealthTracker
from src.risk.kill_switch import KillSwitch


def _build_server(
    *,
    tmp_path: Path,
    api_key: str = "",
    queue_full: bool = False,
) -> tuple[ExecutionControlServer, list[Signal], dict[str, float]]:
    received: list[Signal] = []
    marks: dict[str, float] = {}

    async def enqueue_signal(signal: Signal) -> int:
        if queue_full:
            raise asyncio.QueueFull()
        received.append(signal)
        return len(received)

    def update_mark(symbol: str, price: float) -> None:
        marks[symbol] = price

    tracker = HealthTracker(HealthSnapshot())
    kill_switch = KillSwitch(initial_state=False, kill_file=str(tmp_path / "KILL_TEST"))
    positions: dict[str, int] = {}

    server = ExecutionControlServer(
        tracker=tracker,
        kill_switch=kill_switch,
        enqueue_signal=enqueue_signal,
        update_mark=update_mark,
        get_mark_prices=lambda: dict(marks),
        get_positions=lambda: dict(positions),
        host="127.0.0.1",
        port=8080,
        api_key=api_key,
    )
    return server, received, marks


def test_signal_endpoint_enqueues_and_updates_mark(tmp_path: Path) -> None:
    server, received, marks = _build_server(tmp_path=tmp_path)
    client = TestClient(server.app)

    resp = client.post(
        "/signals",
        json={
            "symbol": "aapl",
            "side": "buy",
            "confidence": 0.9,
            "reason": "MODEL_ALPHA",
            "price": 185.5,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["accepted"] is True
    assert payload["symbol"] == "AAPL"
    assert payload["side"] == "BUY"
    assert payload["queue_size"] == 1

    assert len(received) == 1
    assert received[0].symbol == "AAPL"
    assert received[0].side.value == "BUY"
    assert marks["AAPL"] == 185.5


def test_signal_endpoint_returns_429_when_queue_is_full(tmp_path: Path) -> None:
    server, _, _ = _build_server(tmp_path=tmp_path, queue_full=True)
    client = TestClient(server.app)

    resp = client.post(
        "/signals",
        json={"symbol": "AAPL", "side": "BUY", "confidence": 1.0, "reason": "TEST"},
    )

    assert resp.status_code == 429
    assert "queue" in resp.json()["detail"]


def test_api_key_protects_write_routes(tmp_path: Path) -> None:
    server, _, _ = _build_server(tmp_path=tmp_path, api_key="secret")
    client = TestClient(server.app)

    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    denied = client.post(
        "/signals",
        json={"symbol": "AAPL", "side": "BUY", "confidence": 1.0, "reason": "TEST"},
    )
    assert denied.status_code == 401

    allowed = client.post(
        "/signals",
        headers={"X-API-Key": "secret"},
        json={"symbol": "AAPL", "side": "BUY", "confidence": 1.0, "reason": "TEST"},
    )
    assert allowed.status_code == 200

