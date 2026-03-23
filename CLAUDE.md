# CLAUDE.md

## Project Overview

Real-time arbitrage detection bot for Bitcoin 1-Hour Price markets between **Polymarket** and **Kalshi** prediction markets. When the combined cost of opposite positions across exchanges falls below $1.00 (the guaranteed minimum payout), a risk-free profit exists.

See `thesis.md` for the mathematical foundation.

## Architecture

```
External APIs (Polymarket, Kalshi, Binance)
        │
        ├── fetch_current_polymarket.py   # Polymarket + Binance data
        ├── fetch_current_kalshi.py       # Kalshi + Binance data
        │
        └── get_current_markets.py        # Coordinates market URLs/slugs
                │
        ┌───────┴────────┐
        │                │
    api.py          arbitrage_bot.py
    (FastAPI :8000)  (CLI monitor)
        │
    frontend/        (Next.js :3000, polls API every 1s)
```

**Two interfaces** serve the same arbitrage logic:
- `api.py` — FastAPI server exposing `GET /arbitrage`, consumed by the frontend
- `arbitrage_bot.py` — CLI tool for headless monitoring with console output

**URL generators** (pure functions):
- `find_new_market.py` — Polymarket slug: `bitcoin-up-or-down-{month}-{day}-{hour}{am/pm}-et`
- `find_new_kalshi_market.py` — Kalshi slug: `kxbtcd-{YY}{mmm}{DD}{HH}`

## Tech Stack

| Layer    | Technology                                  |
|----------|---------------------------------------------|
| Backend  | Python 3.9+, FastAPI, Uvicorn, Requests     |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui |
| Testing  | pytest, pytest-mock, httpx (TestClient)      |

## Directory Structure

```
backend/
  api.py                        # FastAPI server (main entry point)
  arbitrage_bot.py              # CLI bot with 1s polling loop
  fetch_current_polymarket.py   # Polymarket + Binance data fetching
  fetch_current_kalshi.py       # Kalshi + Binance data fetching
  get_current_markets.py        # Market URL coordination
  find_new_market.py            # Polymarket slug generation
  find_new_kalshi_market.py     # Kalshi slug generation
  requirements.txt
  tests/
    conftest.py                 # Shared fixtures and mock data
    test_api.py                 # 28 tests
    test_arbitrage_bot.py       # 22 tests
    test_fetch_current_kalshi.py    # 18 tests
    test_fetch_current_polymarket.py # 22 tests
    test_find_new_market.py         # 14 tests
    test_find_new_kalshi_market.py  # 11 tests
    test_get_current_markets.py     # 6 tests

frontend/
  app/
    page.tsx                    # Main dashboard (client component)
    layout.tsx                  # Root layout with Geist fonts
  components/ui/                # shadcn/ui components (badge, button, card, progress, table)
  lib/utils.ts                  # Utility functions (cn/clsx)
  package.json
```

## Commands

### Backend

```bash
# Install dependencies
cd backend && pip install -r requirements.txt

# Run API server (localhost:8000)
python3 api.py

# Run CLI bot (continuous 1s polling)
python3 arbitrage_bot.py

# Run all tests (121 tests)
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_api.py -v

# Run tests matching a pattern
python -m pytest tests/ -k "test_arbitrage" -v
```

### Frontend

```bash
cd frontend && npm install

# Dev server (localhost:3000)
npm run dev

# Production build
npm run build && npm start

# Lint
npm run lint
```

## Code Conventions

### Python (Backend)

- **Style**: PEP 8
- **Error pattern**: Functions return `(data, error_string)` tuples instead of raising exceptions. The API collects errors into a response array.
- **HTTP requests**: All external calls use a 10-second timeout
- **No `eval()`**: Use `json.loads()` for parsing JSON strings
- **Fee constants**: Polymarket 2% on profit, Kalshi 7% on profit
- **Price sanity check**: Up + Down prices must be between 0.85 and 1.15; outside this range indicates stale data

### TypeScript (Frontend)

- **Components**: React functional components with hooks, `"use client"` directive
- **Styling**: Tailwind CSS utility classes via shadcn/ui component library
- **State**: `useState` for local state, no external state management
- **Data fetching**: `setInterval` polling (1s) with `fetch` API against `localhost:8000`

### Testing

- All external HTTP calls are mocked — zero real network requests
- Fixtures in `conftest.py` provide standardized mock data
- Test files mirror source modules (e.g., `test_api.py` tests `api.py`)
- Use `@patch` decorators for mocking, `pytest-mock` for fixtures
- When adding new external API calls, always add corresponding mocked tests

## Key Domain Concepts

- **Strike price**: The BTC price threshold a market resolves around
- **Up/Down (Polymarket)**: Binary outcomes — BTC above or below the strike
- **Yes/No (Kalshi)**: Binary outcomes — equivalent to Up/Down
- **Arbitrage opportunity**: When buying opposite positions across exchanges costs < $1.00
- **Market timing**: Polymarket uses the current hour; Kalshi uses current hour + 1 (offset)
- **Slug generation**: Market URLs are deterministic from timestamps, using ET timezone

## API Response Shape

`GET /arbitrage` returns:

```json
{
  "timestamp": "ISO string",
  "polymarket": { "price_to_beat": 97000, "current_price": 96850, "prices": {"Up": 0.55, "Down": 0.45}, "slug": "..." },
  "kalshi": { "event_ticker": "...", "current_price": 96850, "markets": [{"strike": 97000, "yes_bid": 0.40, ...}] },
  "checks": [{ "poly_strike": 97000, "kalshi_strike": 97000, "poly_leg": "Down", "kalshi_leg": "Yes", "total_cost": 0.85, ... }],
  "opportunities": [],
  "errors": []
}
```

## Common Pitfalls

- Both `api.py` and `arbitrage_bot.py` contain parallel arbitrage logic — changes to comparison/fee logic must be updated in both files
- Polymarket CLOB prices use best ask; Kalshi uses bid/ask spread — don't mix them
- Timezone handling is critical: slugs use ET, internal logic uses UTC. Always use `pytz` for conversions
- The Kalshi market offset (+1 hour) is intentional — their market windows differ from Polymarket's
- `ask=0` means no liquidity — skip that leg rather than treating it as free
