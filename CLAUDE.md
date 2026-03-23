# CLAUDE.md — Project Context for AI Assistants

## Project Overview

Bitcoin arbitrage detection bot comparing hourly prediction markets on **Polymarket** and **Kalshi**. The bot is **read-only** — it detects opportunities but does not execute trades. No API keys are required; all endpoints are public.

## Architecture

```
frontend/ (Next.js dashboard, polls /arbitrage every 1s)
    └── http://localhost:3000

backend/ (Python FastAPI)
    ├── api.py                          # GET /arbitrage endpoint (http://localhost:8000)
    ├── arbitrage_bot.py                # CLI bot (continuous polling loop)
    ├── fetch_current_polymarket.py     # Polymarket Gamma + CLOB + Binance fetching
    ├── fetch_current_kalshi.py         # Kalshi markets + Binance fetching
    ├── get_current_markets.py          # Generates market slugs/tickers from current time
    ├── find_new_market.py              # Polymarket slug generator
    ├── find_new_kalshi_market.py       # Kalshi ticker generator
    └── tests/
        ├── conftest.py                 # Shared fixtures
        ├── test_*.py                   # 121 unit tests
        ├── test_integration.py         # 14 integration tests (full pipeline, mocked HTTP)
        ├── test_e2e_recorded.py        # 4 VCR cassette tests
        ├── test_e2e_live.py            # 5 live smoke tests (gated by RUN_LIVE_TESTS=1)
        └── fixtures/                   # JSON fixture files for integration tests
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
- **Arbitrage logic**: If Poly cost + Kalshi cost < $1.00 for complementary contracts, risk-free profit exists. Fees: Polymarket ~2%, Kalshi ~7%.
- **Time handling**: All slugs use Eastern Time (ET). Polymarket uses current hour; Kalshi uses next hour's identifier.

## Common Commands

```bash
# Run the API server
cd backend && python api.py

# Run the CLI bot
cd backend && python arbitrage_bot.py

# Run unit tests only
cd backend && pytest tests/ -m "not integration and not live" -v

# Run unit + integration tests (CI-safe)
cd backend && pytest tests/ -m "not live" -v

# Run all tests including live smoke tests
cd backend && RUN_LIVE_TESTS=1 pytest tests/ -v

# Start frontend dashboard (requires API server running)
cd frontend && npm run dev
```

## Testing

- **135 offline tests** (121 unit + 14 integration), all pass in ~0.5s
- Integration tests mock at `requests.get` level, letting all internal logic run naturally
- Live tests are gated by `RUN_LIVE_TESTS=1` and skip gracefully on network errors
- pytest markers: `integration`, `live` (configured in `backend/pyproject.toml`)

## Code Conventions

- Error handling: Functions return `(data, error_msg)` tuples
- All HTTP calls use `requests.get()` with `timeout=10`
- No logging module — uses `print()` for console output
- Prices are in dollars (0.00-1.00 range) after normalization
