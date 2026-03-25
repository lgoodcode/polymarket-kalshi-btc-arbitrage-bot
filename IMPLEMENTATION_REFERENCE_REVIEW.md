# Implementation Reference Review

> **Date**: March 25, 2026
> **Source document**: "Polymarket-Kalshi BTC Arbitrage Bot — Complete Implementation Reference" (March 24, 2026)
> **Scope**: Section-by-section validation against the current codebase

---

## Status Dashboard

| # | Claim | Accuracy | Severity | Action | Status |
|---|-------|----------|----------|--------|--------|
| 1.1 | Fee model is wrong | Partially correct | Moderate | Fix now | [x] DONE |
| 1.2 | Kalshi legacy fields dead code | Correct | Low | Fix now | [x] DONE |
| 1.3 | Best ask ignores depth | Correct | Moderate | Fix now | [x] DONE |
| 1.4 | Bot is read-only | Correct (by design) | N/A | No action | [x] N/A |
| 1.5 | Polling too slow | Partially correct | Low | Defer | [x] N/A |
| 1.6 | Float precision | Correct | Low (detection) | Defer | [x] N/A |
| 2 | Fee formulas reference | Reference material | — | Use for 1.1 fix | [x] N/A |
| 3 | Net profit formula | Reference material | — | Use for 1.1 fix | [x] N/A |
| 4–6 | Execution (Poly/Kalshi/Cross) | Future feature | — | Defer | [x] N/A |
| 7 | Order book depth | Partially actionable | Moderate | Fix now (detection side) | [x] DONE |
| 8 | WebSocket streaming | Future feature | — | Defer | [x] N/A |
| 9 | Risk management | Future feature | — | Defer | [x] N/A |
| 10 | Kelly criterion | Future feature | — | Defer | [x] N/A |
| 11 | Resolution divergence | Important reference | — | Document only | [x] N/A |
| 12 | Regulatory/tax | Informational | — | No action | [x] N/A |
| 13 | Infrastructure | Future feature | — | Defer | [x] N/A |
| 14 | Implementation checklist | Roadmap | — | Reorganize in NEXT_STEPS.md | [x] N/A |

---

## Section 1: Critical Code Issues — Detailed Validation

### 1.1 Fee Model Is Wrong

**Claim**: Flat rates `POLYMARKET_FEE_RATE = 0.02` and `KALSHI_FEE_RATE = 0.07` are incorrect; real formulas use parabolic `P*(1-P)`.

**Validation**: `config.py:40-42` defines flat rates. `arbitrage.py:9-17` applies them as `profit * rate` (i.e., `(1.00 - cost) * rate`). This is a linear-on-profit model.

**Accuracy**: **Partially correct**.
- Polymarket: The current 2% on profit is a reasonable approximation. The actual formula uses a category-specific multiplier applied to `price * (1-price)`, making the effective rate vary with price. Peak rate at p=0.50 is ~1.56% (crypto category, pre-March 30) — the 2% flat rate *overestimates* fees, which is conservative.
- Kalshi: The 7% flat on profit is inaccurate. Kalshi's actual formula is `0.07 * count * price * (1 - price)`, rounded up to the next cent. The parabolic shape means fees are highest at p=0.50 and decrease toward extremes. The flat 7% significantly overestimates fees at price extremes.

**Action**: Replace `estimate_fees()` in `arbitrage.py` with parabolic formulas. Update `config.py` to remove flat rate constants in favor of the multiplier-based approach.

**Files**: `arbitrage.py:9-17`, `config.py:40-42`, `test_arbitrage.py`

---

### 1.2 Kalshi Legacy Fields Are Dead Code

**Claim**: `fetch_current_kalshi.py` has a fallback for integer cent fields removed from Kalshi's API on March 12, 2026.

**Validation**: `fetch_current_kalshi.py:72-82` has an `if "yes_ask_dollars" in m` / `else` branch. The `else` branch (lines 77-82) handles legacy integer cent fields (`yes_bid`, `yes_ask`, etc.) that no longer exist in API responses. This has been dead code for 13 days.

**Accuracy**: **Correct**. The CLAUDE.md itself documents that these fields were removed March 12, 2026. Tests in `conftest.py` still include legacy-format fixtures.

**Action**: Remove the `else` branch in `fetch_current_kalshi.py`. Update `conftest.py` fixtures to use only `_dollars` format. Remove any tests that specifically test the legacy path.

**Files**: `fetch_current_kalshi.py:77-82`, `tests/conftest.py`, `tests/test_fetch_current_kalshi.py`

---

### 1.3 Polymarket Best Ask Without Depth Check

**Claim**: `fetch_current_polymarket.py` uses `min(float(a["price"]) for a in asks)` — ignoring order size.

**Validation**: `fetch_current_polymarket.py:24` confirms exactly this. The `size` field is available in CLOB responses (confirmed by `conftest.py` fixture: `{"price": "0.47", "size": "150"}`) but is discarded.

**Accuracy**: **Correct**. A 1-share ask at $0.40 would register as the "best ask" even though it represents negligible liquidity. For a detection bot, this means reported opportunities may be based on illiquid prices.

**Action**: Enrich `get_clob_price()` to return depth information alongside best ask. Propagate through the API response so users can assess opportunity quality. The core detection logic does not need to change — depth is informational.

**Files**: `fetch_current_polymarket.py:17-29`, `api.py`, `arbitrage_bot.py`, `tests/conftest.py`, `tests/test_fetch_current_polymarket.py`, `tests/test_api.py`

---

### 1.4 Bot Is Read-Only

**Claim**: No trade execution exists. Detection without execution = $0 profit.

**Validation**: Correct — no execution code exists anywhere in the codebase.

**Accuracy**: **Correct, but this is intentional**. CLAUDE.md states: "The bot is read-only — it detects opportunities but does not execute trades." This is an architectural decision, not a bug.

**Action**: No action. Execution is a future phase (see `NEXT_STEPS.md`).

---

### 1.5 Polling Instead of WebSockets

**Claim**: 5-second polling is too slow; arb windows last 2–7 seconds.

**Validation**: `config.py:52` sets `POLL_INTERVAL = 5`. No WebSocket code exists. The interval is configurable via env var.

**Accuracy**: **Partially correct**. The 2–7 second window claim applies to *execution* timing. For a detection bot alerting humans, 5 seconds is reasonable — humans cannot act faster. Reducing the interval would increase API call volume and rate-limiting risk (429 handling already exists in `http_utils.py:17-56`).

**Action**: Defer. The interval is already configurable. WebSocket streaming belongs in the execution phase.

---

### 1.6 Float Precision for Financial Math

**Claim**: All price arithmetic uses Python `float`; must use `decimal.Decimal`.

**Validation**: Confirmed — zero `Decimal` imports in the entire backend. All prices parsed with `float()`. Rounding via `round(value, 4)` in `arbitrage.py:17,24`.

**Accuracy**: **Correct, but low severity for detection**. Maximum float error on values in 0.00–1.00 range is ~1e-15. The `round()` calls mitigate the worst cases. Margins of 0.01–0.10 are unaffected by float imprecision. For *execution* with real money, `Decimal` would be essential.

**Action**: Defer to execution phase. The refactor touches every file handling prices (`arbitrage.py`, `fetch_current_kalshi.py`, `fetch_current_polymarket.py`, `binance.py`, `api.py`, `arbitrage_bot.py`, `config.py`, plus all tests) — high effort, low value for detection.

---

## Sections 2–3: Fee Formulas and Net Profit

**Role**: Reference material for implementing the 1.1 fix.

**Key formulas to implement**:
- Kalshi taker: `fee = ceil_to_cent(0.07 * count * price * (1 - price))`
- Kalshi maker: `fee = ceil_to_cent(0.0175 * count * price * (1 - price))`
- Polymarket taker: `fee = count * price * feeMultiplier * price * (1 - price)` where `feeMultiplier` varies by category (crypto = 0.0624, increasing to 0.0720 on March 30)
- Polymarket maker: zero fees

**Net profit**: `$1.00 - P_poly - P_kalshi - Fee_poly - Fee_kalshi - gas`

**Break-even**: Taker-both needs ~5% spread; maker-Poly + taker-Kalshi needs ~3%.

**Accuracy note**: The fee tables and formulas in the reference doc appear well-researched. The worked example in Section 3.2 is internally consistent. The March 30 fee increase date should be verified against Polymarket's current fee schedule.

---

## Sections 4–6: Execution (Polymarket, Kalshi, Cross-Platform)

**Role**: Future feature — aspirational execution architecture.

**Validation**: All API endpoints, authentication methods (Kalshi RSA-PSS, Polymarket L2 credentials), order types (FOK, GTC, IOC), and SDK references appear plausible and well-documented.

**Key items for future reference**:
- Polymarket uses `py-clob-client` SDK; requires Ethereum private key + Polygon wallet
- Kalshi uses RSA-PSS signed headers; demo environment available at `demo-api.kalshi.co`
- Cross-platform strategy: maker on Polymarket (zero fees) + taker on Kalshi (IOC) is optimal
- Rollback logic needed when one leg fills and other doesn't

**Action**: Deferred to `NEXT_STEPS.md` Phase 2.

---

## Section 7: Order Book Depth Analysis

**Role**: Partially actionable now for detection enrichment.

**Validation**: The `effective_fill_price()` function in the reference doc walks order book levels with volume-weighted average pricing. This is more sophisticated than needed for detection but the concept of checking depth is valid.

**Actionable piece**: Report the size available at best ask alongside the price. The reference doc's $50 minimum depth threshold is a useful heuristic for filtering noise.

**Action**: Implement depth reporting as part of the 1.3 fix. Full book-walking can wait for execution phase.

---

## Section 8: WebSocket Streaming

**Role**: Future feature — replaces HTTP polling.

**Validation**: WebSocket endpoints referenced (`wss://ws-subscriptions-clob.polymarket.com/ws/market` for Polymarket, `wss://api.elections.kalshi.com/trade-api/ws/v2` for Kalshi) appear correct based on public API documentation.

**Action**: Deferred to `NEXT_STEPS.md` Phase 3.

---

## Sections 9–10: Risk Management and Kelly Criterion

**Role**: Future feature — only relevant with execution.

**Validation**: The circuit breakers, position limits, and quarter-Kelly sizing are standard quantitative trading practices. The Polymarket heartbeat kill switch (auto-cancel after ~15s without heartbeat) is a real feature worth noting.

**Action**: Deferred to `NEXT_STEPS.md` Phase 4.

---

## Section 11: Resolution Divergence Risk

**Role**: Important reference — relevant even for detection.

**Key insight**: Polymarket settles on Binance BTC/USDT candle data; Kalshi settles on CF Benchmarks Real-Time Index (60-second average from multiple exchanges). These **can diverge** during volatile periods. The 2024 Government Shutdown case (Polymarket YES, Kalshi NO on the "same" event) demonstrates real risk.

**Impact on detection**: Opportunities near resolution time may not be true arbitrage if settlement sources diverge. This should be noted in the bot's output or documentation as a caveat.

**Action**: No code change needed for detection. Add a note to `USAGE.md` or API response about settlement source differences. Critical for execution phase.

---

## Section 12: Regulatory and Tax

**Role**: Informational reference only. No code changes.

**Key notes**: Both platforms are now CFTC-regulated (Kalshi since 2020, Polymarket via QCEX acquisition July 2025). Cross-platform arbitrage is permitted. The "Prediction Markets Are Gambling Act" (March 2026) is worth monitoring.

---

## Section 13: Infrastructure and Deployment

**Role**: Future feature — deployment architecture.

**Action**: Deferred to `NEXT_STEPS.md` Phase 5.

---

## Section 14: Implementation Checklist

**Role**: Roadmap reorganized into `NEXT_STEPS.md`.

The reference doc's 5-phase checklist maps to our phased plan. See `NEXT_STEPS.md` for the reorganized version with current-state context.

---

## Actionable Fix Summary

Ordered by priority for the current detection bot:

| # | Fix | Effort | Files |
|---|-----|--------|-------|
| 1 | Remove Kalshi legacy cent fields | Small | `fetch_current_kalshi.py`, `conftest.py`, `test_fetch_current_kalshi.py` |
| 2 | Improve fee estimation formula | Small | `arbitrage.py`, `config.py`, `test_arbitrage.py` |
| 3 | Add order book depth to output | Medium | `fetch_current_polymarket.py`, `api.py`, `arbitrage_bot.py`, `conftest.py`, multiple test files |

**Verification after all fixes**: `pytest tests/ -m "not live" -v` — all 146+ tests pass.
