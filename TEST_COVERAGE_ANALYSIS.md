# Test Coverage Analysis

## Current State

**Backend:** 121 tests across 7 test files covering all 7 core modules.
**Frontend:** 0 tests, no test framework configured.

### Backend Test Inventory

| Test File | Tests | Module Covered |
|-----------|-------|----------------|
| `test_api.py` | 47 | `api.py` (FastAPI endpoint, fees) |
| `test_arbitrage_bot.py` | 19 | `arbitrage_bot.py` (CLI bot) |
| `test_fetch_current_kalshi.py` | 25 | `fetch_current_kalshi.py` |
| `test_fetch_current_polymarket.py` | 26 | `fetch_current_polymarket.py` |
| `test_find_new_kalshi_market.py` | 9 | `find_new_kalshi_market.py` |
| `test_find_new_market.py` | 9 | `find_new_market.py` |
| `test_get_current_markets.py` | 8 | `get_current_markets.py` |

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

### 2. Backend Integration Tests (MEDIUM)

All API tests mock at the `fetch_*_data_struct` level. No test exercises the full pipeline (HTTP mock → parsing → arbitrage detection). Integration tests mocking at the `requests.get` level would catch bugs between modules.

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
