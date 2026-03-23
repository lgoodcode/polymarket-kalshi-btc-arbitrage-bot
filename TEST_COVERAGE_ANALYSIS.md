# Test Coverage Analysis

## Current State

**Backend:** 144 tests across 10 test files covering all core modules + integration/E2E.
**Frontend:** 0 tests, no test framework configured.

### Backend Test Inventory

| Test File | Tests | Category |
|-----------|-------|----------|
| `test_api.py` | 28 | Unit: FastAPI endpoint, fees |
| `test_arbitrage_bot.py` | 22 | Unit: CLI bot |
| `test_fetch_current_kalshi.py` | 18 | Unit: Kalshi API parsing |
| `test_fetch_current_polymarket.py` | 22 | Unit: Polymarket/CLOB/Binance |
| `test_find_new_kalshi_market.py` | 11 | Unit: Kalshi slug generation |
| `test_find_new_market.py` | 14 | Unit: Polymarket slug generation |
| `test_get_current_markets.py` | 6 | Unit: Market URL coordination |
| `test_integration.py` | 14 | Integration: Full pipeline (mocked HTTP) |
| `test_e2e_recorded.py` | 4 | Tier 2: VCR cassette schema validation |
| `test_e2e_live.py` | 5 | Tier 3: Live API smoke tests |
| **Total** | **144** | 135 pass offline, 4 skipped (no cassettes), 5 live-only |

### Recent Changes
- **Kalshi API migration**: Updated from integer cent fields to `_dollars` string fields (March 2026 breaking change)
- **Integration tests**: 14 tests exercising full pipeline from time→slug→HTTP→arbitrage→response
- **Live smoke tests**: 5 tests hitting real APIs, gated by `RUN_LIVE_TESTS=1`

### Untested Backend Files

| File | Lines | Notes |
|------|-------|-------|
| `fetch_data.py` | 121 | Legacy data fetcher — has own implementations of functions also in other modules |
| `explore_api.py` | 33 | Developer utility |
| `explore_kalshi_api.py` | 48 | Developer utility |
| `inspect_clob.py` | 24 | Developer utility |
| `search_markets.py` | 34 | Developer utility |

---

## Recommended Improvements (Priority Order)

### 1. Frontend Tests (HIGH)

The dashboard (`frontend/app/page.tsx`, ~300 lines) has no test coverage and no test framework configured. Key areas:

- **Data fetching & polling** — `fetchData()` on 1s interval, state updates, error handling
- **`bestOpp` calculation** — `reduce()` selecting highest-margin opportunity
- **Conditional rendering** — loading state, error banner, empty data, opportunity hero card
- **Kalshi market filtering** — `Math.abs(strike - price_to_beat) < 2500` filter in render

**Action:** Add Vitest + React Testing Library. Create `__tests__/page.test.tsx`.

### 2. Backend Integration Tests (DONE)

~~All API tests mock at the `fetch_*_data_struct` level. No test exercises the full pipeline.~~

**Implemented**: 14 integration tests in `test_integration.py` mock at `requests.get` level, exercising the full pipeline. Covers arb found, no arb, API failures, stale prices, unpriced markets, equal strikes, fee erosion, timeouts, CLI bot output, and market window selection.

### 3. Tests for `fetch_data.py` (MEDIUM)

121 lines with its own `get_polymarket_data`, `get_binance_current_price`, `get_binance_open_price`, and `main()`. If still in use, needs tests. If legacy/dead code, should be removed.

### 4. Missing Edge Cases in Existing Tests (MEDIUM)

- **CORS headers** — no test verifies CORS middleware is working on API responses
- **Unsorted Kalshi markets** — no test sends unsorted markets to verify the sort in `api.py`
- **HTTP error responses** — `get_clob_price` tested for empty data but not for 404/500 responses
- **`parse_strike` malformed input** — not tested with `"above $96,250"`, `"$96250"` (no comma), or empty strings
- **`main()` normal flow** — `arbitrage_bot.py` main loop only tested for exceptions, not a normal iteration

### 5. Fee Rounding Edge Cases (LOW)

`_estimate_fees` uses `round(..., 4)` but no test exercises floating-point boundary conditions (very small costs like `0.001`, costs producing fees that require rounding).

### 6. Developer Utility Scripts (LOW)

`explore_api.py`, `explore_kalshi_api.py`, `inspect_clob.py`, `search_markets.py` — low priority since they don't affect production.
