# Trade Executor (IBKR)

Python execution service for algorithmic trading.

This repo is designed to be the "execution side":
- External strategy/AI system generates signals
- This service receives signals via HTTP
- Applies risk checks
- Sends orders to IBKR (paper/live)
- Persists audit trail in SQLite

## Core Features

- Signal ingestion API (`POST /signals`)
- Mark/price ingestion API (`POST /marks`)
- Health + kill switch API (`GET /health`, `POST /kill`)
- Hard risk limits (daily loss, max positions, notional caps)
- IBKR bracket entry orders (TP/SL) and market exit orders
- SQLite logs for `signals/orders/fills`
- Optional Telegram notifications

## Project Layout

```text
src/
  app.py
  settings.py
  logging_conf.py
  common/
  control/
  execution/
  monitoring/
  risk/
  data/store.py
scripts/
tests/
```

## Quick Start

1. Copy env file:

```bash
cp .env.example .env
```

2. Fill required values:

- `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`
- `TRADING_MODE=paper` (recommended first)
- risk limits
- optional `CONTROL_API_KEY` for write-route auth

3. Install:

```bash
pip install -e .
```

4. Run:

```bash
python -m src.app
```

Default API address: `http://0.0.0.0:8080`

## API

### `GET /health`
Runtime state snapshot:
- `control_server_ready`
- `ibkr_connected`
- `signal_queue_size`
- `last_signal_ts_ms`
- `kill_switch`

### `POST /marks`
Upsert latest price used for risk sizing.

Example:

```json
{
  "symbol": "AAPL",
  "price": 185.50
}
```

### `POST /signals`
Send a strategy signal for execution.

Example:

```json
{
  "symbol": "AAPL",
  "side": "BUY",
  "confidence": 0.92,
  "reason": "MODEL_ALPHA_V2",
  "price": 185.50
}
```

Notes:
- `price` is optional but recommended. If provided, it updates mark price first.
- `side` supports `BUY` / `SELL` (case-insensitive).

### `POST /kill`
Activates kill switch and blocks new orders.

## API Auth (Optional)

If `CONTROL_API_KEY` is set, write routes require:

`X-API-Key: <CONTROL_API_KEY>`

Routes requiring key:
- `POST /signals`
- `POST /marks`
- `POST /kill`

## Example: Strategy Repo -> Executor

```bash
curl -X POST http://127.0.0.1:8080/signals \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","side":"BUY","confidence":0.9,"reason":"LLM_SIGNAL","price":185.4}'
```

## Storage

Default: `sqlite:///./executor.db`

Tables:
- `signals`
- `orders`
- `fills`

(`bars` table remains in schema for compatibility but is not used by the execution flow.)

## Scripts

Safety checks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-safety.ps1
```

If `CONTROL_API_KEY` is set:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-safety.ps1 -ApiKey "<YOUR_KEY>"
```

Manual one-order test through `ExecutionEngine`:

```powershell
python .\scripts\test_single_order.py --symbol AAPL --side buy --price 260
```

## Tests

```bash
pytest
```

## Docker

```bash
docker compose up --build
```

## Risk Notice

Use `paper` mode first. Live trading has operational and market risks (slippage, disconnects, config/model errors).
