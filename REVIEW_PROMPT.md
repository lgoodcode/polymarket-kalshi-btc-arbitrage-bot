# Trading Bot Code Review Prompt

Use this prompt to review the Polymarket-Kalshi BTC Arbitrage Bot for correctness before running it. Paste the contents of the source files listed below along with this prompt into your review session.

---

## System Context

This bot monitors two binary options platforms — **Polymarket** and **Kalshi** — that both offer hourly Bitcoin price markets. Each market is a binary contract paying exactly **$1.00** if its condition is met, $0.00 otherwise.

**Arbitrage thesis**: If we can buy complementary legs across the two platforms for a combined cost < $1.00, the minimum payout is guaranteed to be $1.00, yielding risk-free profit.

| Condition | Strategy | Minimum Payout |
|-----------|----------|----------------|
| Poly Strike > Kalshi Strike | Buy Poly DOWN + Kalshi YES | $1.00 |
| Poly Strike < Kalshi Strike | Buy Poly UP + Kalshi NO | $1.00 |
| Poly Strike == Kalshi Strike | Check both combos above | $1.00 |

**Current state**: The bot is **detection-only** — it identifies opportunities but does NOT place orders.

### File Structure

| File | Role |
|------|------|
| `backend/api.py` | FastAPI server; core arbitrage comparison logic |
| `backend/arbitrage_bot.py` | CLI loop; same logic, prints to console |
| `backend/fetch_current_polymarket.py` | Fetches Polymarket CLOB prices + Binance BTC price |
| `backend/fetch_current_kalshi.py` | Fetches Kalshi market quotes |
| `backend/get_current_markets.py` | Determines which hourly market to target |
| `backend/find_new_market.py` | Generates Polymarket market slugs from timestamps |
| `backend/find_new_kalshi_market.py` | Generates Kalshi event tickers from timestamps |
| `thesis.md` | Arbitrage theory documentation |

---

## Review Rules

Review every source file against the rules below. For each rule, cite **specific file paths and line numbers** with your finding.

### Category 1: Arbitrage Logic Correctness

- [ ] **1.1** Verify leg pairing: When `poly_strike > kalshi_strike`, the bot buys **Poly DOWN + Kalshi YES**. Confirm this is correct by tracing through all three price scenarios (price < Kalshi strike, price in middle, price >= Poly strike) and proving minimum payout = $1.00.
- [ ] **1.2** Verify the inverse: When `poly_strike < kalshi_strike`, the bot buys **Poly UP + Kalshi NO**. Trace through all three scenarios.
- [ ] **1.3** Verify equal-strike handling: When strikes are equal, both combos (Down+Yes and Up+No) are checked independently. Confirm neither combo can yield > $1.00 minimum payout (it should be exactly $1.00, not $2.00, since strikes are equal).
- [ ] **1.4** Confirm the arbitrage threshold: `total_cost < 1.00` is the correct condition. Verify margin = `1.00 - total_cost`.
- [ ] **1.5** Check that the `api.py` logic and `arbitrage_bot.py` logic produce **identical results** for the same inputs. Any divergence is a bug.
- [ ] **1.6** In `api.py`, verify that the equal-strike branch uses `continue` correctly and doesn't also fall through to the bottom `if check_data["total_cost"] < 1.00` block (which would double-count).

### Category 2: Price Data Integrity

- [ ] **2.1** Confirm Polymarket prices come from **best ask** (lowest sell offer), since we are buying. Verify `get_clob_price()` returns ask, not bid.
- [ ] **2.2** Confirm Kalshi prices are converted from **cents to dollars** correctly (`yes_ask / 100.0`, `no_ask / 100.0`). A missed division by 100 would produce wildly wrong results.
- [ ] **2.3** Audit the `eval()` calls on lines 59-60 of `fetch_current_polymarket.py`. These parse `clobTokenIds` and `outcomes` from API responses. Determine if this is a correctness risk (wrong parsing) or only a security risk.
- [ ] **2.4** Check what happens when `get_clob_price()` returns `None` (API failure). The caller sets price to `0.0` — this makes any leg using that price appear artificially cheap, potentially signaling a **false arbitrage**. Assess severity.
- [ ] **2.5** Check what happens when Kalshi returns `yes_ask: 0` or `no_ask: 0` (market not yet priced). Same false-arbitrage risk as 2.4.
- [ ] **2.6** Verify Polymarket outcome ordering: the code assumes `outcomes[0]` maps to `clob_token_ids[0]`. If the API returns them in a different order (e.g., ["Down", "Up"] instead of ["Up", "Down"]), prices would be swapped silently.

### Category 3: Market & Time Alignment

- [ ] **3.1** Verify that Polymarket and Kalshi are targeting the **same expiration hour**. The code uses `target_time` for Polymarket and `target_time + 1 hour` for Kalshi. Confirm this offset is correct by checking the market naming conventions on both platforms.
- [ ] **3.2** Verify the Polymarket slug generation: e.g., for a market at 2:00 PM ET, does the slug correctly produce `bitcoin-up-or-down-march-22-2pm-et`?
- [ ] **3.3** Verify the Kalshi ticker generation: e.g., for the same market, does the ticker correctly produce `KXBTCD-26MAR2214` (or appropriate format)?
- [ ] **3.4** Check timezone handling: the code uses `pytz.utc` and converts to `US/Eastern`. Verify DST is handled correctly (Eastern can be UTC-4 or UTC-5).
- [ ] **3.5** Verify that `price_to_beat` (Binance 1h candle open) corresponds to the **same hour** that the Polymarket market uses as its strike. If Polymarket uses a different price feed or rounding, the strike shown may not match.

### Category 4: Fee & Slippage Accounting

- [ ] **4.1** Check if trading fees from either platform are deducted from the margin calculation. Document the actual fee structures for Polymarket and Kalshi binary options. If fees are not deducted, calculate the minimum margin needed to be profitable after fees.
- [ ] **4.2** Check if the bot considers **orderbook depth**. If the best ask has only $10 of liquidity, the bot would report an arbitrage that can only be executed for $10 total, not unlimited size.
- [ ] **4.3** Assess whether the **bid-ask spread** on either platform is accounted for. The bot uses ask prices for buying — verify it would need to use bid prices if selling/closing a position.
- [ ] **4.4** Check for any rounding errors in the margin calculation. With floating point, `0.48 + 0.51 = 0.99` might not be exact.

### Category 5: Error Handling & Resilience

- [ ] **5.1** Check every `requests.get()` call for a `timeout` parameter. Missing timeouts can cause the bot to hang indefinitely.
- [ ] **5.2** Identify all places where exceptions are caught and silently swallowed (returning `None`, `0.0`, or empty defaults). List each one.
- [ ] **5.3** Check if the 1-second polling loop in `arbitrage_bot.py` accounts for the time spent in API calls. If API calls take 3 seconds, the effective interval is 4 seconds, not 1.
- [ ] **5.4** Verify that partial data failures (e.g., Polymarket succeeds but Kalshi fails) are handled without crashing.

### Category 6: Security

- [ ] **6.1** The `eval()` calls in `fetch_current_polymarket.py:59-60` execute arbitrary code from API responses. Assess: could a compromised or malicious API response execute harmful code? Recommend `json.loads()` as a replacement.
- [ ] **6.2** CORS is set to `allow_origins=["*"]`. Assess whether this matters for a locally-run monitoring tool vs. a production deployment.
- [ ] **6.3** Check for any hardcoded secrets, API keys, or credentials in the codebase.

### Category 7: Data Consistency & Race Conditions

- [ ] **7.1** Polymarket and Kalshi data are fetched **sequentially**, not atomically. If prices move between the two fetches, the bot could report an arbitrage that no longer exists (or miss one that briefly existed). Assess the practical risk.
- [ ] **7.2** The frontend polls the backend every 1 second. Check if multiple overlapping requests could cause issues (e.g., if the backend takes > 1 second to respond).
- [ ] **7.3** Verify that the `price_to_beat` (Binance candle open) is fetched at the same time as the market prices. If it's cached or stale, strikes could be misaligned.

### Category 8: Edge Cases

- [ ] **8.1** What happens when Kalshi returns 0 markets for the event ticker? (e.g., market hasn't opened yet)
- [ ] **8.2** What happens when Polymarket's CLOB has no asks (empty orderbook)? The price falls back to `0.0`.
- [ ] **8.3** What happens when the Kalshi subtitle doesn't match the regex `\$([\d,]+)`? The strike becomes `0.0`, which would always satisfy `poly_strike > kalshi_strike`, pairing a $0.00-strike Kalshi YES (which should cost ~$1.00) with Poly DOWN.
- [ ] **8.4** What happens at the hour boundary (e.g., 12:59:59)? Does the bot correctly identify the active market or could it target an expired/not-yet-created market?
- [ ] **8.5** What happens if `poly_up_cost + poly_down_cost` significantly deviates from $1.00? This would indicate stale or incorrect data and should be flagged.

---

## Goal Output: Review Scorecard

Fill out this scorecard after completing the review. Every cell must be filled.

### Summary Table

| # | Category | Rating | Critical Issues | Verdict |
|---|----------|--------|-----------------|---------|
| 1 | Arbitrage Logic Correctness | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 2 | Price Data Integrity | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 3 | Market & Time Alignment | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 4 | Fee & Slippage Accounting | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 5 | Error Handling & Resilience | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 6 | Security | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 7 | Data Consistency | PASS / WARN / FAIL | _count_ | _safe to run?_ |
| 8 | Edge Cases | PASS / WARN / FAIL | _count_ | _safe to run?_ |

### Rating Definitions

- **PASS**: No issues found; logic is correct.
- **WARN**: Issues found but they do not produce incorrect arbitrage signals under normal conditions. Should be fixed before adding execution.
- **FAIL**: Issues found that can produce **false arbitrage signals** or **incorrect margin calculations**. Must be fixed before trusting output.

### Detailed Findings

For each issue found, provide:

```
#### Finding [Category#.Rule#]: [Short Title]
- **Severity**: Critical / High / Medium / Low
- **File**: `path/to/file.py:LINE`
- **Description**: What is wrong
- **Impact**: How this affects arbitrage detection accuracy
- **Recommendation**: Specific fix
```

### Final Verdict

Answer these three questions:

1. **Is the arbitrage math correct?** (Yes/No + explanation)
   - Do the leg pairings guarantee >= $1.00 minimum payout for all price outcomes?
   - Is `total_cost < 1.00` the right threshold?

2. **Can you trust the opportunity signals?** (Yes/No + explanation)
   - Could any data issue cause a false positive (reporting arbitrage that doesn't exist)?
   - Could any data issue cause a false negative (missing real arbitrage)?

3. **Is it safe to run as a monitoring tool?** (Yes/No + conditions)
   - List any must-fix items before running
   - List any must-fix items before adding order execution

---

## Known Issues to Verify

The following potential issues were identified during initial exploration. Confirm or dismiss each:

| # | Issue | File:Line | Status |
|---|-------|-----------|--------|
| K1 | `eval()` used instead of `json.loads()` to parse API data | `fetch_current_polymarket.py:59-60` | _confirm/dismiss_ |
| K2 | `get_clob_price()` returns `None` on failure, caller defaults to `0.0`, creating false-cheap prices | `fetch_current_polymarket.py:38,74-75` | _confirm/dismiss_ |
| K3 | Kalshi `yes_ask`/`no_ask` default to `0` if missing from API response | `fetch_current_kalshi.py:69-72` | _confirm/dismiss_ |
| K4 | No `timeout` on any `requests.get()` call | Multiple files | _confirm/dismiss_ |
| K5 | Kalshi strike regex returns `0.0` on parse failure, not `None` | `fetch_current_kalshi.py:37` | _confirm/dismiss_ |
| K6 | Fees not deducted from margin calculation | `api.py:142`, `arbitrage_bot.py:90` | _confirm/dismiss_ |
| K7 | Kalshi uses `target_time + 1hr` offset — verify this correctly aligns with Polymarket's market | `get_current_markets.py:21` | _confirm/dismiss_ |
| K8 | `poly_up_cost + poly_down_cost` not validated to be ~$1.00 (sanity check) | Not implemented | _confirm/dismiss_ |
| K9 | Floating point comparison `total_cost < 1.00` could have precision issues | `api.py:118,133,140` | _confirm/dismiss_ |

---

## Files to Include in Review Session

Paste the full contents of these files when using this prompt:

1. `backend/api.py`
2. `backend/arbitrage_bot.py`
3. `backend/fetch_current_polymarket.py`
4. `backend/fetch_current_kalshi.py`
5. `backend/get_current_markets.py`
6. `backend/find_new_market.py`
7. `backend/find_new_kalshi_market.py`
8. `thesis.md`
