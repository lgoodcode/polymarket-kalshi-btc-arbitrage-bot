# Test Coverage Analysis

## Current State

**Backend:** 155 tests across 11 test files covering all core modules + integration/E2E.
**Frontend:** 0 tests, no test framework configured.

### Backend Test Inventory

| Test File | Tests | Category |
|-----------|-------|----------|
| `test_api.py` | 27 | Unit: FastAPI endpoint, caching, response structure |
| `test_arbitrage.py` | 14 | Unit: Shared fee estimation + arbitrage comparison engine |
| `test_arbitrage_bot.py` | 18 | Unit: CLI bot output, error handling, main loop |
| `test_fetch_current_kalshi.py` | 16 | Unit: Kalshi API parsing, subtitle parsing, Binance |
| `test_fetch_current_polymarket.py` | 16 | Unit: Polymarket/CLOB/Binance (async) |
| `test_find_new_kalshi_market.py` | 11 | Unit: Kalshi slug generation |
| `test_find_new_market.py` | 14 | Unit: Polymarket slug generation |
| `test_get_current_markets.py` | 6 | Unit: Market URL coordination |
| `test_integration.py` | 14 | Integration: Full pipeline (mocked async) |
| `test_e2e_recorded.py` | 4 | Tier 2: VCR cassette schema validation |
| `test_e2e_live.py` | 5 | Tier 3: Live API smoke tests |
| **Total** | **~155** | 146 pass offline, 4 skipped (no cassettes), 5 live-only |

### Architecture (post-refactor)

The codebase was refactored to use:
- **async/aiohttp** for all HTTP fetching (parallel Polymarket + Kalshi via `asyncio.gather()`)
- **Shared modules**: `arbitrage.py` (fee/comparison engine), `binance.py` (Binance API), `http_utils.py` (retry logic), `config.py` (centralized config), `log_config.py` (logging)
- **pytest-asyncio** with `asyncio_mode = "auto"` for async test support
- **AsyncMock** for mocking async functions in tests

### Test Commands

```bash
# Unit tests only (fast, ~130 tests)
pytest tests/ -m "not integration and not live" -v

# Unit + integration tests (146 tests, CI-safe)
pytest tests/ -m "not live" -v

# All tests including live smoke tests (requires network)
RUN_LIVE_TESTS=1 pytest tests/ -v

# Run specific test file
pytest tests/test_arbitrage.py -v
```

---

## VCR Cassette Tests (test_e2e_recorded.py) — 4 tests, SKIPPED

These tests validate recorded API responses and are **skipped** because no cassettes have been recorded yet. They are valuable for:
- Catching API response format changes (e.g., Kalshi dropping fields)
- Reproducible regression testing without network access
- Schema validation against real API data

### How to Record Cassettes

1. Ensure you have network access to all three APIs (Polymarket, Kalshi, Binance)
2. Run: `RUN_LIVE_TESTS=1 pytest tests/test_e2e_recorded.py --vcr-record=new_episodes -v`
3. Cassettes will be saved to `tests/cassettes/` as YAML files
4. Commit the cassettes so future runs replay them offline

### Current VCR Test Coverage

| Test | What It Validates |
|------|-------------------|
| `test_recorded_full_pipeline` | Fixture files load and have expected structure |
| `test_recorded_response_schema_polymarket` | Gamma API schema: events → markets → clobTokenIds |
| `test_recorded_response_schema_kalshi` | Kalshi API schema: _dollars fields present, values 0-1 |
| `test_recorded_price_reasonableness` | CLOB asks 0-1, BTC 10K-500K, Kalshi yes+no ≈ 1.00 |

### VCR + Async Note

The current VCR tests use static fixture files (not actual cassette playback). To enable true cassette recording/replay with aiohttp, you'll need `vcrpy` with aiohttp support. The `aioresponses` library can also serve as an alternative for mocking HTTP responses at the aiohttp level.

---

## Live Smoke Tests (test_e2e_live.py) — 5 tests, LIVE ONLY

These hit real APIs to verify connectivity and response schemas. Gated by `RUN_LIVE_TESTS=1`.

| Test | What It Validates |
|------|-------------------|
| `test_live_polymarket_gamma_reachable` | Gamma API returns events with markets |
| `test_live_polymarket_clob_reachable` | CLOB returns order book (bids/asks) |
| `test_live_kalshi_markets_reachable` | Kalshi returns markets with _dollars fields |
| `test_live_binance_price_reachable` | Binance returns BTC price in reasonable range |
| `test_live_full_pipeline_smoke` | Both fetch functions return valid structured data |

**Note**: The live full-pipeline test calls async `fetch_*_data_struct()` functions. It uses `asyncio.run()` to execute them since pytest-asyncio auto mode handles this.

---

## Recommended Improvements (Priority Order)

### 1. Frontend Tests (HIGH)

The dashboard (`frontend/app/page.tsx`, ~300 lines) has no test coverage. Key areas:

- **Data fetching & polling** — `fetchData()` on 5s interval, state updates, error handling
- **`bestOpp` calculation** — `reduce()` selecting highest-margin opportunity
- **Conditional rendering** — loading state, error banner, stale indicator, opportunity hero card
- **Data staleness display** — `dataAgeMs` counter, stale badge
- **Fee disclaimer display** — shown when present in API response

**Action:** Add Vitest + React Testing Library. Create `__tests__/page.test.tsx`.

### 2. Record VCR Cassettes (HIGH)

The 4 VCR tests exist but are skipped because no cassettes have been recorded. Recording them provides:
- Offline regression testing against real API response shapes
- Early detection of API changes (Kalshi/Polymarket/Binance)
- Reproducible test data that doesn't depend on fixture maintenance

**Action:** Run `RUN_LIVE_TESTS=1 pytest tests/test_e2e_recorded.py --vcr-record=new_episodes -v` from a network-connected environment. Commit cassettes.

### 3. http_utils.py Retry Logic Tests (MEDIUM)

`http_utils.fetch_json()` has retry with exponential backoff and 429 detection, but no direct unit tests for:
- Successful retry after transient failure
- 429 rate limit triggering longer backoff
- Max retries exhausted → raises last error
- Different error types (ClientError, TimeoutError)

**Action:** Add `tests/test_http_utils.py` with `aioresponses` mocks.

### 4. config.py Tests (MEDIUM)

`config.py` loads from environment variables with defaults. No tests verify:
- Default values are correct
- Environment variable overrides work
- `.env` file loading (when python-dotenv is available)

**Action:** Add `tests/test_config.py` with `monkeypatch` for env vars.

### 5. Health Check Endpoint Tests (MEDIUM)

`GET /health` pings external APIs but has no unit tests. Should test:
- All services healthy → `{"status": "healthy"}`
- One service down → `{"status": "degraded"}`
- Timeout handling

**Action:** Add tests in `test_api.py` using `aioresponses` to mock health check requests.

### 6. log_config.py Tests (LOW)

`log_config.py` sets up logging handlers. Could test:
- Log file creation in configured directory
- JSON format output
- Rotation behavior

**Action:** Add `tests/test_log_config.py` if log reliability becomes critical.

### 7. Missing Edge Cases (LOW)

- **CORS headers** — no test verifies CORS middleware is applied correctly
- **Server-side cache** — no test verifies cache TTL behavior (fresh vs stale)
- **`parse_strike` edge cases** — decimals (`$96,250.50`), currency words (`96250 USD`)
- **Fee rounding boundaries** — very small costs like `0.001`
