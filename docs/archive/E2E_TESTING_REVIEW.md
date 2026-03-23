# E2E & Integration Testing Review

## Status: IMPLEMENTED

All three tiers of E2E/integration tests have been implemented:
- **Tier 1**: 14 mock-based integration tests in `backend/tests/test_integration.py`
- **Tier 2**: 4 VCR cassette tests in `backend/tests/test_e2e_recorded.py`
- **Tier 3**: 5 live smoke tests in `backend/tests/test_e2e_live.py`

Additionally, the **Kalshi API migration** from integer cent fields to `_dollars` string fields has been completed in `fetch_current_kalshi.py` with backward compatibility.

See [USAGE.md](USAGE.md) for test run commands.

## Original Executive Summary

**Yes, we can implement comprehensive E2E dry-run tests.** The bot is a read-only detection tool (no trade execution), all three external APIs (Polymarket Gamma, Polymarket CLOB, Kalshi, Binance) have **public, unauthenticated read endpoints**, and the architecture is well-suited for both mock-based integration tests and live dry-run tests.

**No API keys are required** for the bot's current functionality. All endpoints used are public.

---

## 1. Current State Analysis

### Architecture Overview

```
┌──────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Frontend    │────▶│   FastAPI Backend     │────▶│  External APIs   │
│  (Next.js)   │     │   GET /arbitrage      │     │  - Polymarket    │
│  polls /1s   │     │                        │     │  - Kalshi        │
└──────────────┘     │  arbitrage_bot.py     │     │  - Binance       │
                     │   (CLI, polls /1s)    │     └─────────────────┘
                     └──────────────────────┘
```

### Data Flow (End-to-End)

1. `get_current_market_urls()` → generates Polymarket slug + Kalshi event ticker from current time
2. `fetch_polymarket_data_struct()` → Gamma API → CLOB API → Binance klines + price
3. `fetch_kalshi_data_struct()` → Kalshi markets API → Binance price
4. Arbitrage logic compares strikes and costs across platforms
5. Results returned via FastAPI `/arbitrage` endpoint or printed by CLI bot

### Existing Test Coverage

| Test File | Tests | What's Covered |
|-----------|-------|----------------|
| `test_api.py` | 28 | Fee calculation, arbitrage detection, API response structure, sanity checks |
| `test_arbitrage_bot.py` | 22 | CLI bot logic, error handling, fee labeling |
| `test_fetch_current_polymarket.py` | 22 | CLOB price parsing, Gamma API, Binance data |
| `test_fetch_current_kalshi.py` | 18 | Kalshi API parsing, strike extraction, Binance |
| `test_find_new_market.py` | 14 | Polymarket slug generation, timezone/DST |
| `test_find_new_kalshi_market.py` | 11 | Kalshi slug generation, 24-hour format |
| `test_get_current_markets.py` | 6 | Market URL coordination, hour flooring |
| **Total** | **121** | All pass (0.63s) |

### What's Missing

- **No integration tests** — modules are tested in isolation; no test verifies the full pipeline
- **No E2E tests** — no test calls `/arbitrage` with realistic multi-layer mocked data
- **No live dry-run mode** — no way to hit real APIs and validate the full pipeline
- **No recorded response tests** — no cassette/snapshot testing with real API responses
- **No frontend tests** — no tests for the Next.js dashboard

---

## 2. External API Documentation Review

### Polymarket APIs

#### Gamma API (`https://gamma-api.polymarket.com`)
- **Authentication:** None required (fully public)
- **Used endpoint:** `GET /events?slug={slug}`
- **Rate limits:** Not officially documented; community reports suggest generous limits for read ops
- **Sandbox:** No public testnet; read-only access works on production without auth
- **Key data returned:** Event metadata, market IDs, `clobTokenIds`, `outcomes`

#### CLOB API (`https://clob.polymarket.com`)
- **Authentication:** None for read-only endpoints (order book, prices); EIP-712 + HMAC for trading
- **Used endpoint:** `GET /book?token_id={id}`
- **Rate limits:** Not explicitly documented; WebSocket recommended for high-frequency
- **Sandbox:** No public testnet for CLOB read endpoints
- **Key data returned:** Order book with bids/asks (price + size)

**Sources:**
- [Polymarket Documentation](https://docs.polymarket.com/)
- [Polymarket Authentication](https://docs.polymarket.com/developers/CLOB/authentication)
- [Fetching Markets](https://docs.polymarket.com/market-data/fetching-markets)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)

### Kalshi API

#### Trade API v2 (`https://api.elections.kalshi.com/trade-api/v2`)
- **Authentication:** RSA-PSS signing for trading; **public/unauthenticated for `GetMarkets`**
- **Used endpoint:** `GET /markets?limit=100&event_ticker={ticker}`
- **Rate limits:** Documented in API; generous for market data
- **Demo environment:**
  - Web UI: `https://demo.kalshi.co/`
  - API: `https://demo-api.kalshi.co/trade-api/v2`
  - Mirrors production with play money
  - Requires separate demo account + API key (RSA key pair)
- **Key data returned:** Market list with `subtitle`, `yes_bid`, `yes_ask`, `no_bid`, `no_ask`

**Sources:**
- [Kalshi API Docs - Demo Environment](https://docs.kalshi.com/getting_started/demo_env)
- [Kalshi API Keys](https://docs.kalshi.com/getting_started/api_keys)
- [Kalshi API Guide](https://zuplo.com/learning-center/kalshi-api)

### Binance API

#### Spot API v3 (`https://api.binance.com/api/v3`)
- **Authentication:** None for public market data
- **Used endpoints:**
  - `GET /ticker/price?symbol=BTCUSDT` (current price)
  - `GET /klines?symbol=BTCUSDT&interval=1h&startTime={ms}&limit=1` (historical candle)
- **Rate limits:** 1200 req/min for IP-based; 6000 weight/min
- **Sandbox:** `https://testnet.binance.vision/api/v3` (limited data availability)

---

## 3. API Keys & Credentials Required

### Current Bot (Read-Only Detection) — NO KEYS NEEDED

| API | Endpoint Used | Auth Required | Keys Needed |
|-----|--------------|---------------|-------------|
| Polymarket Gamma | `GET /events` | No | None |
| Polymarket CLOB | `GET /book` | No | None |
| Kalshi Trade v2 | `GET /markets` | No | None |
| Binance Spot v3 | `GET /ticker/price`, `GET /klines` | No | None |

**The bot can run entirely without any API keys, secrets, or environment variables.** All four APIs used are public, unauthenticated endpoints for market data.

### If Trade Execution Were Added (Future)

| Platform | Auth Method | What You'd Need |
|----------|------------|-----------------|
| Polymarket | EIP-712 + HMAC | Ethereum private key, derived L2 API credentials (apiKey, secret, passphrase), USDC on Polygon |
| Kalshi | RSA-PSS signing | Kalshi account, RSA key pair (generated in dashboard), Key ID |
| Kalshi (Demo) | Same as above | Separate demo account at `demo.kalshi.co`, separate RSA key pair |

---

## 4. E2E Testing Strategy — Three Tiers

### Tier 1: Mock-Based Integration Tests (Recommended — implement first)

**Goal:** Test the full pipeline end-to-end with deterministic, controlled data.

**Approach:** Mock at the HTTP boundary (`requests.get`) with realistic multi-API response chains. Unlike current unit tests which mock individual functions, these tests mock only HTTP calls and let all internal logic run naturally.

```python
# Example: Full pipeline integration test
@patch('fetch_current_kalshi.requests.get')
@patch('fetch_current_polymarket.requests.get')
def test_full_arbitrage_pipeline(mock_poly_requests, mock_kalshi_requests):
    """
    Test the entire pipeline: time → slug generation → API fetch →
    arbitrage detection → response formatting.
    """
    # Mock ALL HTTP calls with realistic responses
    # Let slug generation, parsing, arbitrage logic run for real
    ...
```

**What it validates:**
- Slug generation produces correct URLs for the current time
- HTTP response parsing works correctly across all APIs
- Data flows correctly between modules (Polymarket → arbitrage engine ← Kalshi)
- Arbitrage logic produces correct results with realistic price data
- Fee estimation integrates correctly
- API response structure matches frontend expectations

**Benefits:**
- No network access needed (works in CI, sandboxed environments)
- Deterministic — same inputs always produce same outputs
- Fast (~1s)
- Can test edge cases impossible to reproduce with live data (market gaps, stale prices, etc.)

### Tier 2: Recorded Response Tests (VCR/Cassette Style)

**Goal:** Use captured real API responses for high-fidelity testing.

**Approach:** Record actual API responses once, replay them in tests. Use `vcrpy` or `responses` library.

```python
# Record once: capture real API responses to YAML/JSON cassettes
# Replay forever: tests use cassettes instead of live APIs

@vcr.use_cassette('cassettes/btc_arbitrage_march_23_2pm.yaml')
def test_real_market_data_pipeline():
    """Test with actual recorded API responses."""
    data = get_arbitrage_data_for_time(fixed_time)
    assert data["polymarket"] is not None
    assert data["kalshi"] is not None
    assert len(data["checks"]) > 0
```

**What it validates:**
- Real API response formats haven't changed (regression detection)
- Parser handles actual production JSON structures
- Real price data produces sensible arbitrage results

**Benefits:**
- High fidelity — uses real data shapes
- Detects API schema changes
- Still deterministic and offline-capable

### Tier 3: Live Dry-Run Tests (Smoke Tests)

**Goal:** Hit real APIs, validate the full pipeline against live markets.

**Approach:** Call real APIs with no trading, just validate data retrieval and processing.

```python
@pytest.mark.live
@pytest.mark.skipif(os.environ.get('RUN_LIVE_TESTS') != '1', reason="Live tests disabled")
def test_live_full_pipeline():
    """Smoke test: hit real APIs and validate data."""
    from api import get_arbitrage_data
    result = get_arbitrage_data()

    assert "timestamp" in result
    assert result["polymarket"] is not None or len(result["errors"]) > 0
    assert result["kalshi"] is not None or len(result["errors"]) > 0

    if result["polymarket"] and result["kalshi"]:
        assert "prices" in result["polymarket"]
        assert "markets" in result["kalshi"]
        assert len(result["checks"]) > 0
        # Validate price reasonableness
        poly_sum = result["polymarket"]["prices"]["Up"] + result["polymarket"]["prices"]["Down"]
        assert 0.80 <= poly_sum <= 1.20
```

**What it validates:**
- APIs are reachable and responding
- Current market slugs resolve to real events
- Live prices are parseable and reasonable
- Full pipeline works against production APIs

**Constraints:**
- Requires network access (not for CI)
- Results are non-deterministic (prices change)
- Markets only exist for current/future hours
- Rate limit aware

---

## 5. Specific Test Scenarios to Implement

### Integration Test Scenarios (Tier 1)

| # | Scenario | What It Tests |
|---|----------|---------------|
| 1 | **Happy path: Arbitrage detected** | Full pipeline with prices that produce arbitrage |
| 2 | **Happy path: No arbitrage** | Full pipeline with prices where total_cost > $1.00 |
| 3 | **Polymarket API down** | Graceful error propagation through full pipeline |
| 4 | **Kalshi API down** | Graceful error propagation through full pipeline |
| 5 | **Binance API down** | Pipeline continues with None prices, no crash |
| 6 | **Stale Polymarket prices** | Sanity check catches Up+Down != ~$1.00 |
| 7 | **Unpriced Kalshi markets** | Markets with 0 asks are skipped |
| 8 | **Multiple Kalshi strikes** | Correct market selection window (±4 around closest) |
| 9 | **Equal strikes** | Both Down+Yes and Up+No combinations checked |
| 10 | **Fee erosion** | Arbitrage exists pre-fees but not post-fees |
| 11 | **Timezone/DST boundary** | Slug generation at DST transitions |
| 12 | **API response format change** | Parser handles missing/extra fields gracefully |
| 13 | **Full API response → Frontend** | TestClient GET /arbitrage returns valid JSON matching frontend expectations |
| 14 | **CLI bot output** | check_arbitrage() prints correct format with real-shaped data |

### End-to-End Scenarios (Tier 2/3)

| # | Scenario | What It Tests |
|---|----------|---------------|
| 15 | **Recorded real session** | Full pipeline with cassette from real API responses |
| 16 | **Live smoke test** | Hit all 4 APIs, validate response structure |
| 17 | **Market hour boundary** | Test at :59 and :00 to verify slug transitions |
| 18 | **Weekend/off-hours** | Behavior when markets may not exist |

---

## 6. Implementation Recommendations

### File Structure
```
backend/tests/
├── conftest.py                          # Existing shared fixtures
├── test_api.py                          # Existing unit tests (28)
├── test_arbitrage_bot.py                # Existing unit tests (22)
├── test_fetch_current_polymarket.py     # Existing unit tests (22)
├── test_fetch_current_kalshi.py         # Existing unit tests (18)
├── test_find_new_market.py              # Existing unit tests (14)
├── test_find_new_kalshi_market.py       # Existing unit tests (11)
├── test_get_current_markets.py          # Existing unit tests (6)
├── test_integration.py                  # NEW: Tier 1 mock-based integration tests
├── test_e2e_recorded.py                 # NEW: Tier 2 recorded response tests
├── test_e2e_live.py                     # NEW: Tier 3 live dry-run smoke tests
├── cassettes/                           # NEW: Recorded API responses (Tier 2)
│   └── btc_arb_session_*.yaml
└── fixtures/                            # NEW: Realistic multi-API response sets
    ├── realistic_poly_gamma.json
    ├── realistic_poly_clob_up.json
    ├── realistic_poly_clob_down.json
    ├── realistic_kalshi_markets.json
    ├── realistic_binance_price.json
    └── realistic_binance_kline.json
```

### Additional Dependencies
```
# Add to requirements.txt for testing
vcrpy>=6.0.0              # Tier 2: HTTP cassette recording/replay
responses>=0.25.0         # Alternative to vcrpy for simpler response mocking
pytest-timeout>=2.2.0     # Prevent hung tests
```

### pytest Configuration
```ini
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
markers = [
    "live: marks tests that hit real external APIs (deselect with '-m not live')",
    "integration: marks integration tests",
    "slow: marks slow-running tests",
]
```

### Running Tests
```bash
# Unit tests only (existing, fast)
pytest tests/ -m "not live and not integration"

# Unit + integration tests (CI-safe)
pytest tests/ -m "not live"

# All tests including live smoke tests
RUN_LIVE_TESTS=1 pytest tests/ -m ""

# Live tests only
RUN_LIVE_TESTS=1 pytest tests/ -m live -v
```

---

## 7. Key Findings & Risks

### Positive
1. **No authentication needed** — all APIs are public for read-only, eliminating credential management for testing
2. **Stateless architecture** — no database, no sessions, no side effects; ideal for testing
3. **Clean module separation** — each data source is independently testable
4. **Existing 121 unit tests** — solid foundation to build integration tests on top of

### Risks & Concerns
1. **CRITICAL: Kalshi integer cents fields being removed (March 12, 2026)** — Kalshi is migrating from legacy integer fields (`yes_bid`, `yes_ask`, `no_bid`, `no_ask` in cents) to new `_fp` (fixed-point) and `_dollars` variants. The bot reads the legacy fields in `fetch_current_kalshi.py:68-73`. This may already be broken or will break imminently. Must verify and migrate to new field names.
2. **Kalshi subpenny pricing** — As of March 9, 2026, Kalshi supports fractional pricing on select markets (`fractional_trading_enabled` flag). The bot's cents-to-dollars conversion (`/ 100.0`) may need updating.
3. **Kalshi API URL is fine** — `api.elections.kalshi.com` works for all markets (not just elections), confirmed as a valid production endpoint alongside `trading-api.kalshi.com`.
4. **No retry/backoff logic** — a single failed API call fails the entire pipeline; integration tests should verify graceful degradation.
5. **Time-dependent slug generation** — tests must freeze time to be deterministic.
6. **Market availability** — live tests only work when BTC hourly markets are active on both platforms.
7. **Proxy/firewall restrictions** — CI environments may block outbound HTTPS (as observed in this environment); live tests must handle this gracefully.

### API Schema Stability
- **Binance:** Very stable v3 API, rarely changes
- **Polymarket Gamma:** Relatively stable, community-supported; rate limit ~4,000 req/10s
- **Polymarket CLOB:** Active development, potential breaking changes; rate limit ~15,000 req/10s general, 50 req/10s for `/book`
- **Kalshi v2:** Active breaking changes in March 2026 (fixed-point migration, subpenny pricing, fractional trading). Historical data now partitioned into live/historical tiers.

---

## 8. Conclusion

The bot is well-positioned for E2E testing because:

1. **Zero credentials needed** — all read-only endpoints are public
2. **Pure computation** — the bot detects but doesn't trade, so tests have no side effects
3. **Kalshi has a full demo environment** at `demo-api.kalshi.co` for future trade execution testing
4. **Polymarket has no public testnet** but read-only endpoints work without auth

**Recommended implementation order:**
1. **Tier 1 first** (mock-based integration) — highest value, works everywhere, CI-safe
2. **Tier 2 second** (recorded responses) — captures real API schemas for regression testing
3. **Tier 3 last** (live smoke tests) — manual validation, not for CI
