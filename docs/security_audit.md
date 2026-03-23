# Security Audit — Polymarket-Kalshi BTC Arbitrage Bot

| Field | Value |
|-------|-------|
| **Version** | 1.0 |
| **Date** | 2026-03-23 |
| **Auditor** | Claude Code (Automated Security Review) |
| **Scope** | Full codebase — backend, frontend, dependencies, data flow |
| **Deployment** | Personal use — local machine or VPS |
| **Bot Type** | Detection-only (no trade execution) |

---

## Executive Summary

This bot monitors BTC binary options markets on Polymarket and Kalshi to identify risk-free arbitrage opportunities. It is currently **read-only** — it fetches prices and reports opportunities but does **not** place orders, move funds, or execute trades.

Despite being detection-only, several findings pose real risk:

- **Data integrity issues** (stale prices, no depth check) could cause a user to act on phantom signals and lose money
- **Legacy files contain `eval()` on untrusted API data** — arbitrary code execution risk on your machine
- **No retry logic or rate-limit handling** means the bot will go blind during peak opportunities
- **No persistent logging** means you can't audit what happened after the fact

**18 total findings**: 3 Critical, 6 High, 6 Medium, 3 Low, plus an informational section on safeguards needed before adding trade execution.

---

## Findings Summary

| ID | Severity | Status | Title | Personal Use? |
|----|----------|--------|-------|---------------|
| SEC-001 | CRITICAL | OPEN | `eval()` code injection in legacy files | YES — runs on your machine |
| SEC-002 | CRITICAL | OPEN | No order book depth/liquidity verification | YES — you'd act on unexecutable signals |
| SEC-003 | CRITICAL | OPEN | Sequential fetching creates stale-price risk | YES — phantom arbitrage signals |
| SEC-004 | HIGH | OPEN | CORS wildcard allows all origins | LOW locally, YES on VPS with open port |
| SEC-005 | HIGH | OPEN | No retry logic or exponential backoff | YES — bot goes blind on transient failures |
| SEC-006 | HIGH | OPEN | Aggressive 1s polling will trigger rate limits | YES — causes cascading API failures |
| SEC-007 | HIGH | OPEN | `price_to_beat` can be None in valid response | YES — could cause wrong strike comparison |
| SEC-008 | HIGH | OPEN | Fee estimation uses flat rates, not real fee schedule | YES — could make losing trades look profitable |
| SEC-009 | HIGH | OPEN | No persistent logging or audit trail | YES — can't debug missed/bad signals |
| SEC-010 | MEDIUM | OPEN | Hardcoded API endpoints across multiple files | YES — maintenance burden |
| SEC-011 | MEDIUM | OPEN | Duplicate `get_binance_current_price()` function | YES — maintenance risk |
| SEC-012 | MEDIUM | OPEN | Binance price fetched twice per scan cycle | YES — wastes rate limit budget |
| SEC-013 | MEDIUM | OPEN | Kalshi subtitle parsing may silently skip markets | YES — could miss valid arbitrage |
| SEC-014 | MEDIUM | OPEN | Frontend hardcoded to `localhost:8000` | Only matters for VPS deployment |
| SEC-015 | MEDIUM | OPEN | No health check endpoint | Only matters for VPS deployment |
| SEC-016 | LOW | OPEN | Unused `httpx` dependency | Minimal risk |
| SEC-017 | LOW | OPEN | No request ID or correlation tracking | Quality-of-life |
| SEC-018 | LOW | OPEN | Legacy files still in repository | YES — contain eval() vulnerability |

---

## Detailed Findings

### CRITICAL

#### SEC-001: `eval()` Code Injection in Legacy Files

- **Files:** `backend/fetch_data.py` lines 31-32, `backend/inspect_clob.py` line 23
- **Relevant for personal use:** YES

```python
# fetch_data.py
outcomes = eval(market.get("outcomes", "[]"))          # Line 31
outcome_prices = eval(market.get("outcomePrices", "[]"))  # Line 32

# inspect_clob.py
token_ids = eval(data[0]['markets'][0]['clobTokenIds'])    # Line 23
```

**Risk:** `eval()` executes arbitrary Python code. If the Polymarket API is compromised, returns unexpected data, or a DNS hijack redirects the request, the response payload is executed as code on your machine. This could lead to:
- File system access (read/write/delete)
- Credential theft
- Reverse shell / remote access
- Cryptocurrency wallet theft

**Mitigating factor:** The active code in `fetch_current_polymarket.py` uses `json.loads()` (safe). But `fetch_data.py` and `inspect_clob.py` are still importable and could be accidentally invoked.

**Recommendation:** Delete legacy files or replace all `eval()` calls with `json.loads()`.

**Resolution:**
- [ ] Remove or fix `fetch_data.py`
- [ ] Remove or fix `inspect_clob.py`

---

#### SEC-002: No Order Book Depth / Liquidity Verification

- **File:** `backend/fetch_current_polymarket.py` line 38, `backend/api.py` lines 104-105
- **Relevant for personal use:** YES

The bot uses `best_ask` price from the CLOB order book but does not check:
- How much volume is available at that price
- Whether the spread is reasonable
- Whether there's enough liquidity to actually fill an order

**Risk:** You see "ARBITRAGE FOUND — $0.02 profit" but there's only $1 of volume at that price. You cannot actually execute the trade, or you get partially filled at a worse price (slippage).

**Example scenario:**
```text
Best ask for Poly Down: $0.470 (but only 5 contracts available)
Best ask for Kalshi Yes: $0.420 (but only 2 contracts available)
You want to buy 100 contracts → actual fill price much higher → loss
```

**Recommendation:** Add minimum volume threshold check. Display available depth alongside price signals. Consider adding a `min_liquidity` parameter.

**Resolution:**
- [ ] Add order book depth to CLOB price fetch
- [ ] Display volume alongside arbitrage signals
- [ ] Add configurable minimum liquidity threshold

---

#### SEC-003: Sequential Data Fetching Creates Stale-Price Risk

- **File:** `backend/api.py` lines 44-45
- **Relevant for personal use:** YES

```python
poly_data, poly_err = fetch_polymarket_data_struct()   # T=0ms
kalshi_data, kalshi_err = fetch_kalshi_data_struct()    # T=100-500ms later
```

Each fetch makes 2-3 HTTP requests. By the time Kalshi data arrives, Polymarket prices may have already moved — especially in volatile BTC markets.

**Risk:** The bot reports arbitrage that no longer exists. If you act on it manually (or via future automation), you buy at a price that's already moved against you.

**Compounding factor:** Within `fetch_polymarket_data_struct()` itself, three separate API calls are made sequentially:
```python
poly_prices, poly_err = get_polymarket_data(slug)        # T=0ms
current_price, curr_err = get_binance_current_price()    # T=100ms
price_to_beat, beat_err = get_binance_open_price(...)    # T=200ms
```

Total window: potentially 500ms+ of price drift across 5+ API calls.

**Recommendation:**
- Use `asyncio` or `concurrent.futures` to fetch Polymarket and Kalshi data in parallel
- Add a staleness indicator (timestamp each data source, show age)
- For future execution: implement a "re-verify" step that re-fetches prices immediately before placing orders

**Resolution:**
- [ ] Parallelize Polymarket and Kalshi data fetching
- [ ] Add per-source timestamps to response
- [ ] Add staleness warning if data age > threshold

---

### HIGH

#### SEC-004: CORS Wildcard Allows All Origins

- **File:** `backend/api.py` line 16
- **Relevant for personal use:** LOW locally, YES on VPS

```python
allow_origins=["*"]
```

Any website can make requests to your API. On localhost this is low risk. On a VPS with the port exposed, anyone can:
- Monitor your arbitrage signals in real-time
- Front-run your trades by watching your bot's output
- If execution is added: potentially trigger actions via CSRF

**Recommendation:** Restrict to `["http://localhost:3000"]` for local dev. Use environment variable for VPS deployments.

**Resolution:**
- [ ] Replace wildcard with specific origin(s)

---

#### SEC-005: No Retry Logic or Exponential Backoff

- **Files:** `backend/fetch_current_polymarket.py`, `backend/fetch_current_kalshi.py`
- **Relevant for personal use:** YES

Every API call is single-attempt. If Binance returns a 500, or Kalshi has a brief outage, the entire scan fails and waits 1 second before trying again with no backoff.

**Risk scenarios:**
- Transient network blip → you miss a real arbitrage window
- API returns 429 (rate limited) → bot keeps hammering at 1/sec → extended blackout
- DNS resolution failure → entire scan cycle returns error

**Recommendation:** Add retry with exponential backoff (e.g., 1s, 2s, 4s) with max 3 retries per call. Detect 429 responses specifically and back off longer.

**Resolution:**
- [ ] Add retry logic with exponential backoff
- [ ] Handle HTTP 429 specifically with longer backoff

---

#### SEC-006: Aggressive 1-Second Polling Will Trigger Rate Limits

- **Files:** `frontend/app/page.tsx` line 65, `backend/api.py` (called per request)
- **Relevant for personal use:** YES

Each frontend poll triggers 5+ external API calls:
1. Polymarket Events API
2. Polymarket CLOB API (x2 for Up/Down tokens)
3. Binance Ticker API (x2 — called by both fetch modules)
4. Binance Klines API
5. Kalshi Markets API

At 1 poll/second = **420+ external requests/minute**.

Binance free tier allows 1,200 requests/minute but that's shared across all endpoints. Kalshi and Polymarket may have lower limits.

**Risk:** Rate limiting causes the bot to return errors, which the frontend silently logs to console. You see stale data and don't realize the bot is blind.

**Recommendation:** Increase poll interval to 5-10 seconds. Add server-side caching with TTL. Show "data age" in the UI so you know if data is stale.

**Resolution:**
- [ ] Increase frontend poll interval to 5-10s
- [ ] Add server-side response caching with configurable TTL
- [ ] Display data staleness indicator in UI

---

#### SEC-007: `price_to_beat` Can Be None in Valid Response

- **File:** `backend/fetch_current_polymarket.py` lines 133-143
- **Relevant for personal use:** YES

```python
price_to_beat, beat_err = get_binance_open_price(target_time_utc)

# beat_err is ignored if poly_prices succeeded
return {
    "price_to_beat": price_to_beat,  # Could be None!
    "current_price": current_price,   # Could be None!
    "prices": poly_prices,
    ...
}, None  # No error returned despite None values
```

If the Binance klines call fails (e.g., the candle hasn't opened yet for a future market), `price_to_beat` is `None`. The downstream code in `api.py:69` checks for this, but the response is still returned as "successful" with partial data.

**Risk:** Edge cases where `price_to_beat` is `None` could lead to incorrect strike comparisons or misleading UI display.

**Recommendation:** Treat any `None` price as an error. Don't return partial data as success.

**Resolution:**
- [ ] Return error when critical price fields are None

---

#### SEC-008: Fee Estimation Uses Flat Rates, Not Real Fee Schedule

- **File:** `backend/api.py` lines 7-9, 22-32
- **Relevant for personal use:** YES

```python
POLYMARKET_FEE_RATE = 0.02  # ~2% on winnings
KALSHI_FEE_RATE = 0.07      # ~7% on profits
```

Real fee structures:
- **Polymarket:** Uses a tiered fee schedule based on price (not a flat 2%). Fees are lower on contracts closer to $0.50 and higher at extremes.
- **Kalshi:** Fees are capped and vary by contract type. The 7% flat rate may overstate fees on small profits and understate on large ones.

**Risk:** A trade that appears profitable after the estimated fees may actually be a loss after real fees. Or vice versa — you skip a truly profitable trade because estimated fees made it look unprofitable.

**Recommendation:** Implement actual fee schedules for both platforms. At minimum, document the inaccuracy and add a disclaimer to the UI.

**Resolution:**
- [ ] Research and implement actual Polymarket fee schedule
- [ ] Research and implement actual Kalshi fee schedule
- [ ] Add fee accuracy disclaimer to UI output

---

#### SEC-009: No Persistent Logging or Audit Trail

- **Files:** All backend files use `print()` only
- **Relevant for personal use:** YES

The bot only outputs to stdout. There is no:
- Log file
- Structured logging (JSON format for parsing)
- Historical record of detected opportunities
- Record of errors or API failures
- Timestamps with timezone info in logs

**Risk:** You can't answer questions like:
- "What opportunities did the bot find while I was sleeping?"
- "How often does the Kalshi API fail?"
- "Was there an arbitrage opportunity at 3:47 AM that I missed?"
- "Is the bot's detection accuracy improving or degrading over time?"

**Recommendation:** Add Python `logging` module with file handler. Log all opportunities, errors, and key metrics. Consider structured JSON logging for easy analysis.

**Resolution:**
- [ ] Add Python logging with file output
- [ ] Log all detected opportunities with full price data
- [ ] Log all API errors with response details

---

### MEDIUM

#### SEC-010: Hardcoded API Endpoints Across Multiple Files

- **Files:** `backend/fetch_current_polymarket.py` lines 9-14, `backend/fetch_current_kalshi.py` lines 8-10, `backend/fetch_data.py` lines 6-9
- **Relevant for personal use:** YES (maintenance burden)

API URLs, fee rates, timeouts, and symbols are hardcoded as module-level constants in multiple files. Changes require editing source code.

**Recommendation:** Centralize configuration in a single `config.py` or use environment variables with `python-dotenv`.

**Resolution:**
- [ ] Create centralized config module or .env support

---

#### SEC-011: Duplicate `get_binance_current_price()` Function

- **Files:** `backend/fetch_current_polymarket.py` lines 83-90, `backend/fetch_current_kalshi.py` lines 13-20
- **Relevant for personal use:** YES (maintenance risk)

Identical function defined in two files. If you fix a bug or change behavior in one, the other remains outdated.

**Recommendation:** Move to a shared utility module (e.g., `backend/utils.py` or `backend/binance.py`).

**Resolution:**
- [ ] Extract shared function to utility module

---

#### SEC-012: Binance Price Fetched Twice Per Scan Cycle

- **Files:** `backend/fetch_current_polymarket.py` line 132, `backend/fetch_current_kalshi.py` line 53
- **Relevant for personal use:** YES (wastes rate limit budget)

Both `fetch_polymarket_data_struct()` and `fetch_kalshi_data_struct()` independently call `get_binance_current_price()`. This doubles the Binance API calls per scan.

**Recommendation:** Fetch Binance price once in the calling code (`api.py`) and pass it to both functions.

**Resolution:**
- [ ] Fetch Binance price once and pass to both modules

---

#### SEC-013: Kalshi Subtitle Parsing May Silently Skip Markets

- **File:** `backend/fetch_current_kalshi.py` lines 32-38
- **Relevant for personal use:** YES

```python
def parse_strike(subtitle):
    match = re.search(r'\$([\d,]+)', subtitle)
    if match:
        return float(match.group(1).replace(',', ''))
    return None  # Silently skipped
```

If Kalshi changes their subtitle format (e.g., "Above $96,250.00" with decimals, or "96250 USD"), the regex won't match and the market is silently excluded.

**Recommendation:** Add logging when `parse_strike` returns `None`. Add test cases for edge case subtitle formats.

**Resolution:**
- [ ] Add warning log when subtitle parsing fails
- [ ] Add edge case test coverage

---

#### SEC-014: Frontend Hardcoded to `localhost:8000`

- **File:** `frontend/app/page.tsx` line 53
- **Relevant for personal use:** Only for VPS deployment

```javascript
const res = await fetch("http://localhost:8000/arbitrage")
```

**Recommendation:** Use environment variable `NEXT_PUBLIC_API_URL` with `localhost:8000` as default.

**Resolution:**
- [ ] Move API URL to environment variable

---

#### SEC-015: No Health Check Endpoint

- **File:** `backend/api.py`
- **Relevant for personal use:** Only for VPS deployment

No `/health` or `/status` endpoint exists. On a VPS, you can't easily verify the bot is running and APIs are reachable.

**Recommendation:** Add a `/health` endpoint that checks connectivity to all external APIs.

**Resolution:**
- [ ] Add health check endpoint

---

### LOW

#### SEC-016: Unused `httpx` Dependency

- **File:** `backend/requirements.txt`
- **Relevant for personal use:** Minimal

`httpx` is listed in requirements but only used in test files (for FastAPI `TestClient`). It's not used in production code.

**Recommendation:** Move to a `requirements-dev.txt` or document as test-only dependency.

**Resolution:**
- [ ] Separate dev/test dependencies

---

#### SEC-017: No Request ID or Correlation Tracking

- **Files:** All backend files
- **Relevant for personal use:** Quality of life

Each scan cycle has no unique identifier. If you're reviewing logs, you can't correlate which Polymarket fetch goes with which Kalshi fetch.

**Recommendation:** Generate a UUID per scan cycle and include in all log entries.

**Resolution:**
- [ ] Add scan cycle ID to logging

---

#### SEC-018: Legacy Files Still in Repository

- **Files:** `backend/fetch_data.py`, `backend/inspect_clob.py`
- **Relevant for personal use:** YES (contains SEC-001 vulnerability)

Both files contain dangerous `eval()` calls (SEC-001). `fetch_data.py` has hardcoded timestamps from November 2025 and appears superseded by `fetch_current_polymarket.py`. `inspect_clob.py` is a debugging/inspection script that also uses `eval()` on API response data.

**Recommendation:** Delete both files entirely, or add prominent deprecation warnings and replace all `eval()` calls with `json.loads()`.

**Resolution:**
- [ ] Delete or neutralize `fetch_data.py`
- [ ] Delete or neutralize `inspect_clob.py`

---

## Informational: Safeguards Required Before Adding Trade Execution

If this bot is ever extended to actually place orders, the following safeguards are **mandatory** to prevent financial loss:

| Safeguard | Description | Priority |
|-----------|-------------|----------|
| **Pre-trade balance check** | Verify sufficient funds on both platforms before placing orders | P0 |
| **Atomic two-leg execution** | Both legs must execute within <100ms to avoid one-sided exposure | P0 |
| **Kill switch** | Manual emergency stop that cancels all pending orders and halts the bot | P0 |
| **Position size limits** | Maximum dollar amount per trade, per hour, and per day | P0 |
| **Circuit breaker** | Auto-halt after N consecutive losses or total loss exceeds threshold | P0 |
| **Slippage protection** | Re-verify price immediately before order placement; abort if price moved | P0 |
| **Order book depth check** | Verify sufficient volume at target price before placing order | P1 |
| **Idempotency keys** | Prevent duplicate orders on retry (use unique order IDs) | P1 |
| **Partial fill handling** | Strategy for when only one leg fills or fills partially | P1 |
| **Position reconciliation** | On startup, check for any open positions from previous runs | P1 |
| **API key security** | Store keys in environment variables or secrets manager, never in code | P1 |
| **Rate limit budget** | Track API call counts and pause before hitting limits | P2 |
| **Profit/loss tracking** | Persistent database of all trades with P&L calculation | P2 |
| **Alerting** | Notifications (email/SMS/Telegram) for opportunities, errors, and losses | P2 |

---

## Existing Safeguards (What's Already Good)

| Safeguard | Location | Status |
|-----------|----------|--------|
| `json.loads()` instead of `eval()` in active code | `fetch_current_polymarket.py:61-62` | IMPLEMENTED |
| 10-second request timeouts | All fetch files (`REQUEST_TIMEOUT = 10`) | IMPLEMENTED |
| Price sanity check (Up + Down ~ $1.00) | `api.py:73-79`, `arbitrage_bot.py:46-49` | IMPLEMENTED |
| Skip unpriced Kalshi legs (0 ask) | `api.py:108-109`, `arbitrage_bot.py:74-76` | IMPLEMENTED |
| Fee estimation in opportunity display | `api.py:22-39`, `arbitrage_bot.py:10-14` | IMPLEMENTED |
| No secrets/API keys in codebase | All files checked | VERIFIED |
| `.gitignore` covers `.env*` files | `frontend/.gitignore` | VERIFIED |
| Comprehensive test suite (121+ tests) | `backend/tests/` | VERIFIED |
| Read-only API access (no POST/PUT/DELETE) | All fetch files | VERIFIED |
| Error propagation to frontend | `api.py:56-59`, `page.tsx:92-104` | IMPLEMENTED |

---

## Resolution Log

Track fixes here as they are applied:

| Date | Finding ID | Action Taken | Verification | Commit |
|------|-----------|--------------|--------------|--------|
| 2026-03-23 | — | Initial audit completed | — | — |

### Verification Commands

Use these commands to verify specific findings have been resolved:

| Finding | Verification Command |
|---------|---------------------|
| SEC-001 | `grep -rn 'eval(' backend/ --include='*.py' \| grep -v test \| grep -v __pycache__` — should return no results |
| SEC-004 | `grep -n 'allow_origins' backend/api.py` — should not contain `"*"` |
| SEC-011 | `grep -rn 'def get_binance_current_price' backend/ --include='*.py' \| grep -v test` — should return exactly 1 result |
| SEC-012 | `grep -rn 'get_binance_current_price()' backend/ --include='*.py' \| grep -v test` — should return exactly 1 call site |
| SEC-018 | `ls backend/fetch_data.py backend/inspect_clob.py 2>&1` — files should not exist |

---

## How to Use This Document

This is a **living document**. Update it as findings are resolved:

1. When you fix an issue, change its **Status** from `OPEN` to `RESOLVED` in the summary table
2. Add a row to the **Resolution Log** with the date, finding ID, action taken, and commit hash
3. If you decide not to fix something, change status to `ACCEPTED RISK` or `WON'T FIX` and document why
4. When new findings are discovered, add them with the next available `SEC-XXX` ID
5. Re-audit periodically, especially after adding new features (particularly trade execution)
