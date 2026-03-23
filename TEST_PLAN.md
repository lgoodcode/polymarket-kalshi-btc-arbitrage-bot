# Comprehensive Review Findings & Unit Test Plan

## Overview

This document captures the full code review findings and test plan for the Polymarket-Kalshi BTC Arbitrage Bot. It is designed to be self-contained so that a separate agent can implement the tests without needing to re-explore the codebase.

---

## Architecture Summary

### Dependency Graph
```
api.py ──────────────────┐
arbitrage_bot.py ────────┤
                         ├── fetch_current_polymarket.py ──┐
                         │                                  ├── get_current_markets.py ──┬── find_new_market.py
                         └── fetch_current_kalshi.py ───────┘                           └── find_new_kalshi_market.py
```

### External APIs
1. **Polymarket Gamma API**: `https://gamma-api.polymarket.com/events`
2. **Polymarket CLOB API**: `https://clob.polymarket.com/book`
3. **Kalshi Trade API**: `https://api.elections.kalshi.com/trade-api/v2/markets`
4. **Binance Spot API**: `https://api.binance.com/api/v3/ticker/price` and `/klines`

### Dependencies (requirements.txt)
```
fastapi>=0.100.0
uvicorn>=0.20.0
requests>=2.31.0
pytz>=2023.3
```

**Test dependencies to add**: `pytest`, `pytest-mock`, `httpx` (for FastAPI TestClient)

---

## File-by-File Function Reference

### 1. `backend/find_new_market.py` — Polymarket Slug Generator

**No external API calls. Pure logic. Easy to test.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `generate_slug(target_time)` | `datetime → str` | e.g. `"bitcoin-up-or-down-november-26-1pm-et"` | Converts to ET. Handles naive datetimes (assumes UTC). |
| `generate_market_url(target_time)` | `datetime → str` | Full URL with BASE_URL prefix | Delegates to `generate_slug` |
| `get_next_market_urls(num_hours=5)` | `int → list[str]` | List of URLs | Uses current time internally |
| `get_current_market_url()` | `None → str` | Single URL | Next hour from now |
| `generate_urls_until_year_end()` | `None → None` | Writes to `market_urls_2025.txt` | Side effect: file I/O |

**Slug format**: `bitcoin-up-or-down-{month_lowercase}-{day}-{hour12}{am/pm}-et`

**Test cases needed**:
- Known input/output: Nov 26 2025 1PM ET → `bitcoin-up-or-down-november-26-1pm-et`
- Midnight: 12AM → `bitcoin-up-or-down-...-12am-et`
- Noon: 12PM → `bitcoin-up-or-down-...-12pm-et`
- Single-digit hours: 1AM-9AM, 1PM-9PM (no leading zero)
- Naive datetime input (should assume UTC, convert to ET)
- Timezone-aware UTC input
- Timezone-aware ET input
- DST transition (e.g., March "spring forward", November "fall back")

---

### 2. `backend/find_new_kalshi_market.py` — Kalshi Slug Generator

**No external API calls. Pure logic. Easy to test.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `generate_kalshi_slug(target_time)` | `datetime → str` | e.g. `"kxbtcd-25nov2614"` | Converts to ET. |
| `generate_kalshi_url(target_time)` | `datetime → str` | Full URL | Delegates to `generate_kalshi_slug` |
| `generate_urls_until_year_end()` | `None → None` | Writes to file | Side effect |

**Slug format**: `kxbtcd-{YY}{mmm}{DD}{HH}` where mmm=3-letter month lowercase, HH=24hr ET

**Test cases needed**:
- Known input: Nov 26 2025 2PM ET → `kxbtcd-25nov2614`
- Midnight: → `...00`
- Single-digit day: pad with 0 (e.g., day 5 → `05`)
- Year rollover: 2026 → `26`
- Naive datetime handling
- DST transitions

---

### 3. `backend/get_current_markets.py` — Market URL Coordinator

**No external API calls. Uses datetime.now() internally.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `get_current_market_urls()` | `None → dict` | `{polymarket: url, kalshi: url, target_time_utc: dt, target_time_et: dt}` | Kalshi uses target_time + 1hr offset |

**Key logic**:
- `target_time = now.replace(minute=0, second=0, microsecond=0)` (current hour floor)
- Polymarket URL uses `target_time`
- Kalshi URL uses `target_time + timedelta(hours=1)` (K7 from review)

**Test cases needed**:
- Mock `datetime.now()` to a known time
- Verify Polymarket and Kalshi URLs are correctly offset by 1 hour
- Verify target_time_utc and target_time_et are correct
- Test at hour boundaries (e.g., 12:00:00, 12:59:59)

---

### 4. `backend/fetch_current_kalshi.py` — Kalshi Data Fetcher

**Makes HTTP requests. Must be mocked in tests.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `get_binance_current_price()` | `None → (float\|None, str\|None)` | BTC price or error | 10s timeout |
| `get_kalshi_markets(event_ticker)` | `str → (list\|None, str\|None)` | Raw market list or error | 10s timeout |
| `parse_strike(subtitle)` | `str → float\|None` | Strike price or None | Regex: `\$([\d,]+)` |
| `fetch_kalshi_data_struct()` | `None → (dict\|None, str\|None)` | Structured data or error | Orchestrator function |

**`parse_strike` test cases** (pure function, no mocking needed):
- `"$96,250 or above"` → `96250.0`
- `"$100,000 or above"` → `100000.0`
- `"$85,000 or above"` → `85000.0`
- `"$500 or above"` → `500.0`
- `"no dollar sign"` → `None`
- `""` (empty string) → `None`
- `"$0 or above"` → result should be 0.0 (but filtered out by caller since `strike > 0`)

**`get_kalshi_markets` test cases** (mock requests):
- Successful response with markets → returns list
- HTTP error (e.g., 500) → returns (None, error_string)
- Timeout → returns (None, error_string)
- Empty markets in response → returns ([], None)

**`fetch_kalshi_data_struct` test cases** (mock internal calls):
- Normal flow: multiple markets, varied strikes → sorted by strike
- Markets with invalid subtitles → filtered out (strike is None)
- Markets with strike = 0 → filtered out
- Empty market list → returns `{"event_ticker": ..., "current_price": ..., "markets": []}`
- Kalshi API error → returns (None, error_string)
- Binance price error → current_price is None but still returns data

---

### 5. `backend/fetch_current_polymarket.py` — Polymarket Data Fetcher

**Makes HTTP requests. Must be mocked in tests.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `get_clob_price(token_id)` | `str → float\|None` | Best ask price or None | Returns 0.0 if asks exist but best_ask is 0 |
| `get_polymarket_data(slug)` | `str → (dict\|None, str\|None)` | Prices dict or error | Uses json.loads (was eval) |
| `get_binance_current_price()` | `None → (float\|None, str\|None)` | BTC price or error | |
| `get_binance_open_price(target_time_utc)` | `datetime → (float\|None, str\|None)` | Candle open price or error | |
| `fetch_polymarket_data_struct()` | `None → (dict\|None, str\|None)` | Structured data or error | Orchestrator |

**`get_clob_price` test cases** (mock requests):
- Normal orderbook: bids and asks present → returns min(asks)
- Empty asks, bids present → returns 0.0
- Empty bids, asks present → returns min(asks)
- Both empty → returns 0.0
- Multiple asks → returns lowest price
- HTTP error → returns None
- Timeout → returns None
- Malformed JSON → returns None

**`get_polymarket_data` test cases** (mock requests):
- Normal flow: event with 2 tokens → returns prices dict
- Event not found (empty response) → returns (None, "Event not found")
- No markets in event → returns (None, "Markets not found in event")
- Unexpected token count (!=2) → returns (None, "Unexpected number of tokens")
- CLOB price fetch failure → returns (None, "Failed to fetch CLOB price for ...")
- Outcomes order: `["Up", "Down"]` vs `["Down", "Up"]` — verify mapping is correct
- Invalid JSON in clobTokenIds → exception caught, returns error

**`get_binance_open_price` test cases** (mock requests):
- Normal kline response → returns open price
- Empty kline data (future timestamp) → returns (None, "Candle not found yet")
- HTTP error → returns (None, error_string)

**`fetch_polymarket_data_struct` test cases** (mock internal calls):
- Normal flow → returns full data dict
- Polymarket error → returns (None, error_string)
- Binance current price error → still returns data (current_price=None)
- Binance open price error → still returns data (price_to_beat=None)

---

### 6. `backend/api.py` — FastAPI Server & Arbitrage Logic

**Key logic to test extensively. Mock the two fetch functions.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `_estimate_fees(poly_cost, kalshi_cost)` | `(float, float) → float` | Estimated fees (rounded 4dp) | Pure function |
| `_add_fee_info(check)` | `dict → None` | Mutates dict in-place | Adds 3 keys |
| `get_arbitrage_data()` | `None → dict` | Full arbitrage response | FastAPI endpoint GET /arbitrage |

**Constants**: `POLYMARKET_FEE_RATE = 0.02`, `KALSHI_FEE_RATE = 0.07`

**`_estimate_fees` test cases** (pure function):
- `(0.50, 0.50)` → `(0.50*0.02) + (0.50*0.07) = 0.01 + 0.035 = 0.045`
- `(0.0, 0.0)` → `(1.0*0.02) + (1.0*0.07) = 0.02 + 0.07 = 0.09`
- `(1.0, 1.0)` → `0 + 0 = 0.0` (no profit, no fees)
- `(1.0, 0.50)` → `0 + 0.035 = 0.035`
- `(0.48, 0.51)` → `(0.52*0.02) + (0.49*0.07) = 0.0104 + 0.0343 = 0.0447`

**`_add_fee_info` test cases**:
- Profitable after fees: margin > est_fees → `profitable_after_fees = True`
- Unprofitable after fees: margin < est_fees → `profitable_after_fees = False`
- Breakeven: margin == est_fees → `profitable_after_fees = False`

**`get_arbitrage_data` — Arbitrage Logic test cases** (mock fetches):

*Error handling:*
- Polymarket fetch error → errors list populated, empty checks/opportunities
- Kalshi fetch error → errors list populated, empty checks/opportunities
- Both errors → both in errors list
- Poly strike is None → error, early return
- Price sanity fail (Up+Down < 0.85) → error, early return
- Price sanity fail (Up+Down > 1.15) → error, early return
- Price sanity pass (Up+Down == 0.0, skipped since `poly_sum > 0` check) → no error

*Market selection:*
- Closest market at index 0 → start_idx=0
- Closest market at end → end_idx=len
- Multiple markets equidistant → first one wins (standard min behavior)
- Empty Kalshi markets → no checks, no opportunities

*Arbitrage detection — Poly > Kalshi strike:*
- `poly_strike=100000, kalshi_strike=99000, poly_down=0.40, kalshi_yes=0.50` → total=0.90, arb found, margin=0.10
- `poly_strike=100000, kalshi_strike=99000, poly_down=0.60, kalshi_yes=0.50` → total=1.10, no arb
- Exactly 1.00 → no arb (strict `< 1.00`)

*Arbitrage detection — Poly < Kalshi strike:*
- `poly_strike=99000, kalshi_strike=100000, poly_up=0.40, kalshi_no=0.50` → total=0.90, arb found
- No arb when total >= 1.00

*Arbitrage detection — Equal strikes:*
- Both combos checked independently
- Only Down+Yes is arb → 1 opportunity
- Only Up+No is arb → 1 opportunity
- Both are arb → 2 opportunities
- Neither is arb → 0 opportunities
- `continue` correctly skips the bottom check_data block (no double-counting)

*Unpriced legs:*
- `yes_ask=0` → market skipped entirely
- `no_ask=0` → market skipped entirely
- Both 0 → skipped

*Fee info on opportunities:*
- Every opportunity dict should have `estimated_fees`, `margin_after_fees`, `profitable_after_fees`
- Non-opportunity checks should NOT have fee fields

---

### 7. `backend/arbitrage_bot.py` — CLI Bot

**Same arbitrage logic as api.py but outputs to console. Mock fetches + capture stdout.**

| Function | Signature | Returns | Notes |
|----------|-----------|---------|-------|
| `_estimate_fees(poly_cost, kalshi_cost)` | `(float, float) → float` | Same as api.py | |
| `check_arbitrage()` | `None → None` | Prints to stdout | |
| `main()` | `None → None` | Infinite loop | Test with single iteration |

**`check_arbitrage` test cases** (mock fetches, capture print output):
- Normal arb found → verify "ARBITRAGE FOUND" in output, fee info printed
- No arb → verify "No risk-free arbitrage found" in output
- Poly error → verify error printed, early return
- Kalshi error → verify error printed, early return
- Missing data → verify "Missing data." printed
- Poly strike None → verify printed
- Price sanity fail → verify WARNING printed
- No Kalshi markets → verify "No Kalshi markets found" printed
- Unpriced legs → verify skipped (no checking output for that market)
- Fee output format: verify "Est. Fees" and "(PROFITABLE)" or "(NOT PROFITABLE)" in output

**`main` test cases**:
- Verify it calls `check_arbitrage` and sleeps
- Verify KeyboardInterrupt exits gracefully
- Verify exceptions are caught and loop continues

---

## Test Infrastructure Setup

### Directory Structure
```
backend/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures and mock data
│   ├── test_find_new_market.py
│   ├── test_find_new_kalshi_market.py
│   ├── test_get_current_markets.py
│   ├── test_fetch_current_kalshi.py
│   ├── test_fetch_current_polymarket.py
│   ├── test_api.py
│   └── test_arbitrage_bot.py
```

### conftest.py Fixtures Needed

```python
# Sample Polymarket data fixture
SAMPLE_POLY_DATA = {
    "price_to_beat": 95000.0,
    "current_price": 95500.0,
    "prices": {"Up": 0.55, "Down": 0.47},
    "slug": "bitcoin-up-or-down-march-22-2pm-et",
    "target_time_utc": "<datetime>"
}

# Sample Kalshi data fixture
SAMPLE_KALSHI_DATA = {
    "event_ticker": "KXBTCD-26MAR2215",
    "current_price": 95500.0,
    "markets": [
        {"strike": 94000.0, "yes_bid": 85, "yes_ask": 87, "no_bid": 12, "no_ask": 14, "subtitle": "$94,000 or above"},
        {"strike": 95000.0, "yes_bid": 50, "yes_ask": 52, "no_bid": 47, "no_ask": 49, "subtitle": "$95,000 or above"},
        {"strike": 96000.0, "yes_bid": 20, "yes_ask": 22, "no_bid": 77, "no_ask": 79, "subtitle": "$96,000 or above"},
    ]
}

# Sample CLOB orderbook response
SAMPLE_CLOB_RESPONSE = {
    "bids": [{"price": "0.45", "size": "100"}, {"price": "0.44", "size": "200"}],
    "asks": [{"price": "0.47", "size": "150"}, {"price": "0.48", "size": "300"}]
}

# Sample Polymarket event API response
SAMPLE_POLY_EVENT_RESPONSE = [{
    "markets": [{
        "clobTokenIds": '["token_up_123", "token_down_456"]',
        "outcomes": '["Up", "Down"]'
    }]
}]

# Sample Kalshi markets API response
SAMPLE_KALSHI_API_RESPONSE = {
    "markets": [
        {"subtitle": "$94,000 or above", "yes_bid": 85, "yes_ask": 87, "no_bid": 12, "no_ask": 14},
        {"subtitle": "$95,000 or above", "yes_bid": 50, "yes_ask": 52, "no_bid": 47, "no_ask": 49},
    ]
}

# Sample Binance responses
SAMPLE_BINANCE_PRICE = {"symbol": "BTCUSDT", "price": "95500.00"}
SAMPLE_BINANCE_KLINE = [[1700000000000, "95000.00", "96000.00", "94500.00", "95800.00", "1000"]]
```

### Mocking Strategy

1. **Pure functions** (slug generators, parse_strike, _estimate_fees): No mocking needed
2. **HTTP functions** (get_clob_price, get_kalshi_markets, etc.): Use `unittest.mock.patch` on `requests.get`
3. **Orchestrator functions** (fetch_*_data_struct): Mock the internal helper functions they call
4. **API endpoint** (get_arbitrage_data): Use FastAPI `TestClient` + mock the two fetch_*_data_struct functions
5. **CLI bot** (check_arbitrage): Mock fetches + use `capsys` to capture stdout
6. **Time-dependent functions**: Use `unittest.mock.patch` on `datetime.datetime.now`

---

## Test Count Estimate

| File | Estimated Tests | Category |
|------|----------------|----------|
| test_find_new_market.py | ~12 | Pure slug generation + timezone |
| test_find_new_kalshi_market.py | ~10 | Pure slug generation + timezone |
| test_get_current_markets.py | ~6 | Time mocking + URL coordination |
| test_fetch_current_kalshi.py | ~18 | parse_strike + API mocking |
| test_fetch_current_polymarket.py | ~22 | CLOB + Polymarket + Binance mocking |
| test_api.py | ~30 | Arbitrage logic + fee calc + endpoint |
| test_arbitrage_bot.py | ~15 | CLI output verification |
| **Total** | **~113** | |

---

## Verification Plan

After implementing tests:
1. Run `cd backend && python -m pytest tests/ -v` — all tests should pass
2. Run `python -m pytest tests/ --tb=short` to verify no import errors
3. Run `python -m pytest tests/ -v --co` (collect only) to verify test discovery
4. Verify no tests make real HTTP calls (all should be mocked)
5. Check coverage with `python -m pytest tests/ --cov=. --cov-report=term-missing` if pytest-cov is available
