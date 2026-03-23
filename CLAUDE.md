# CLAUDE.md

## Project Overview

Real-time arbitrage detection bot for Bitcoin 1-Hour Price markets between **Polymarket** and **Kalshi** prediction markets. When the combined cost of opposite positions across exchanges falls below $1.00 (the guaranteed minimum payout), a risk-free profit exists.

The bot is **read-only** — it detects opportunities but does not execute trades. No API keys are required; all endpoints are public.

See `thesis.md` for the mathematical foundation.

## Architecture

```text
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

**Two interfaces** expose the same core arbitrage engine, but with different market selection behavior:
- `api.py` — FastAPI server exposing `GET /arbitrage`, selects a strike window (±4) around the closest Kalshi market to the Polymarket strike (consumed by the frontend)
- `arbitrage_bot.py` — CLI tool that iterates all fetched Kalshi markets for headless monitoring, filtering only what it prints to the console

**URL generators** (pure functions):
- `find_new_market.py` — Polymarket slug: `bitcoin-up-or-down-{month}-{day}-{hour}{am/pm}-et`
- `find_new_kalshi_market.py` — Kalshi slug: `kxbtcd-{YY}{mmm}{DD}{HH}`

## Tech Stack

| Layer    | Technology                                  |
|----------|---------------------------------------------|
| Backend  | Python 3.9+, FastAPI, Uvicorn, Requests     |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui |
| Testing  | pytest, pytest-mock, httpx, vcrpy            |

## Directory Structure

```text
backend/
  api.py                        # FastAPI server (main entry point)
  arbitrage_bot.py              # CLI bot with 1s polling loop
  fetch_current_polymarket.py   # Polymarket + Binance data fetching
  fetch_current_kalshi.py       # Kalshi + Binance data fetching
  get_current_markets.py        # Market URL coordination
  find_new_market.py            # Polymarket slug generation
  find_new_kalshi_market.py     # Kalshi slug generation
  pyproject.toml                # pytest markers (integration, live)
  requirements.txt
  tests/
    conftest.py                     # Shared fixtures and mock data
    test_api.py
    test_arbitrage_bot.py
    test_fetch_current_kalshi.py
    test_fetch_current_polymarket.py
    test_find_new_market.py
    test_find_new_kalshi_market.py
    test_get_current_markets.py
    test_integration.py             # 14 full-pipeline integration tests
    test_e2e_recorded.py            # VCR cassette replay tests
    test_e2e_live.py                # Live API smoke tests (RUN_LIVE_TESTS=1)
    fixtures/                       # JSON fixture files for integration tests

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
python api.py

# Run CLI bot (continuous 1s polling)
python arbitrage_bot.py

# Run unit tests only (121 tests, fast)
pytest tests/ -m "not integration and not live" -v

# Run unit + integration tests (135 tests, CI-safe)
pytest tests/ -m "not live" -v

# Run all tests including live smoke tests
RUN_LIVE_TESTS=1 pytest tests/ -v

# Run specific test file
pytest tests/test_api.py -v

# Run tests matching a pattern
pytest tests/ -k "test_arbitrage" -v
```

### Frontend

```bash
cd frontend && npm install

# Dev server (localhost:3000, requires API server running)
npm run dev

# Production build
npm run build && npm start

# Lint
npm run lint
```

## External APIs (all public, no auth)

| API | Base URL | Used For |
|-----|----------|----------|
| Polymarket Gamma | `https://gamma-api.polymarket.com/events` | Market metadata, token IDs |
| Polymarket CLOB | `https://clob.polymarket.com/book` | Order book prices |
| Kalshi Trade v2 | `https://api.elections.kalshi.com/trade-api/v2/markets` | Market list, strike prices |
| Binance Spot v3 | `https://api.binance.com/api/v3/` | BTC current price + hourly open |

## Key Technical Details

- **Kalshi API**: Uses `_dollars` string fields (e.g., `"yes_ask_dollars": "0.5600"`). Legacy integer cent fields were removed March 12, 2026. The code has backward compat for both formats in `fetch_current_kalshi.py`.
- **Polymarket prices**: Fetched from CLOB order book (best ask). Up + Down should sum to ~$1.00.
- **Arbitrage logic**: If Poly cost + Kalshi cost < $1.00 for complementary contracts, risk-free profit exists.
- **Time handling**: All slugs use Eastern Time (ET). Polymarket uses current hour; Kalshi uses next hour's identifier (+1 hour offset).

## Code Conventions

### Python (Backend)

- **Style**: PEP 8
- **Error pattern**: Functions return `(data, error_string)` tuples instead of raising exceptions. The API collects errors into a response array.
- **HTTP requests**: In `fetch_current_*` modules, all external calls use `requests.get()` with `timeout=10`
- **No `eval()` in new code**: Use `json.loads()` for parsing JSON strings; legacy scripts (e.g., `fetch_data.py`, `inspect_clob.py`) are temporary exceptions until refactored
- **Fee constants**: Polymarket 2% on profit, Kalshi 7% on profit
- **Price sanity check**: Up + Down prices must be between 0.85 and 1.15; outside this range indicates stale data
- **Console output**: Uses `print()` — no logging module

### TypeScript (Frontend)

- **Components**: React functional components with hooks, `"use client"` directive
- **Styling**: Tailwind CSS utility classes via shadcn/ui component library
- **State**: `useState` for local state, no external state management
- **Data fetching**: `setInterval` polling (1s) with `fetch` API against `localhost:8000`

### Testing

- All external HTTP calls are mocked — zero real network requests in offline tests
- Fixtures in `conftest.py` provide standardized mock data; JSON fixtures in `tests/fixtures/`
- Test files mirror source modules (e.g., `test_api.py` tests `api.py`)
- Use `@patch` decorators for mocking, `pytest-mock` for fixtures
- pytest markers: `integration`, `live` (configured in `backend/pyproject.toml`)
- When adding new external API calls, always add corresponding mocked tests

## Key Domain Concepts

- **Strike price**: The BTC price threshold a market resolves around
- **Up/Down (Polymarket)**: Binary outcomes — BTC above or below the strike
- **Yes/No (Kalshi)**: Binary outcomes — equivalent to Up/Down
- **Arbitrage opportunity**: When buying opposite positions across exchanges costs < $1.00
- **Market timing**: Polymarket uses the current hour; Kalshi uses current hour + 1 (offset)
- **Slug generation**: Market URLs are deterministic from timestamps, using ET timezone

## Common Pitfalls

- Both `api.py` and `arbitrage_bot.py` contain parallel arbitrage logic — changes to comparison/fee logic must be updated in both files
- Polymarket CLOB prices use best ask; Kalshi uses bid/ask spread — don't mix them
- Timezone handling is critical: slugs use ET, internal logic uses UTC. Always use `pytz` for conversions
- The Kalshi market offset (+1 hour) is intentional — their market windows differ from Polymarket's
- `ask=0` means no liquidity — skip that leg rather than treating it as free

## Documentation

### Active docs (repo root)

| File | Purpose |
|------|---------|
| `README.md` | Project overview, setup, how it works |
| `CONTRIBUTING.md` | Contribution guidelines, dev setup, test commands |
| `CLAUDE.md` | AI assistant context (this file) |
| `USAGE.md` | End-user guide: running the bot, understanding output |
| `thesis.md` | Arbitrage theory and math |
| `TEST_COVERAGE_ANALYSIS.md` | Living doc: test inventory, gaps, recommendations |

### Archived docs (`docs/archive/`)

Docs that have served their purpose get moved to `docs/archive/` to keep the repo root clean. These are kept for historical reference but are no longer actively maintained.

| File | Why archived |
|------|-------------|
| `REVIEW_PROMPT.md` | One-time code review checklist; all issues (K1-K9) resolved |
| `PR_SUMMARY.md` | Summary of a specific past PR; historical |
| `TEST_PLAN.md` | Original test plan with estimates; superseded by actual tests |
| `E2E_TESTING_REVIEW.md` | E2E testing proposal; fully implemented |

### Archiving convention

When a doc becomes obsolete (proposal implemented, one-time task completed, superseded by newer doc):
1. `git mv <doc>.md docs/archive/`
2. Update the tables above in this file
3. Do NOT delete — archive preserves history without cluttering the root
