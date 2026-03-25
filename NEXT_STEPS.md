# Next Steps — Arbitrage Bot Roadmap

> **Date**: March 25, 2026
> **Source**: Implementation Reference Review (`IMPLEMENTATION_REFERENCE_REVIEW.md`)
> **Context**: The bot is currently read-only (detection only). This document plans improvements in phases, from immediate detection fixes through aspirational execution features.

---

## Phase 1: Detection Improvements (Actionable Now)

These fixes improve detection accuracy within the current read-only architecture. No new dependencies, no API keys, no scope change.

### 1.1 Remove Kalshi Legacy Integer Cent Fields

- **Why**: Dead code since March 12, 2026. The `else` branch in `fetch_current_kalshi.py:77-82` handles fields that no longer exist in Kalshi API responses.
- **What**: Remove the `else` branch, update `conftest.py` fixtures to `_dollars` format only, remove legacy-specific tests.
- **Files**: `fetch_current_kalshi.py`, `tests/conftest.py`, `tests/test_fetch_current_kalshi.py`
- **Verify**: `pytest tests/test_fetch_current_kalshi.py -v`

### 1.2 Improve Fee Estimation Accuracy

- **Why**: The flat `profit * rate` model in `arbitrage.py:9-17` overestimates fees at price extremes and underestimates near p=0.50. Kalshi uses a parabolic `price * (1-price)` formula.
- **What**: Replace `estimate_fees()` with parabolic formulas. Kalshi taker: `0.07 * price * (1-price)`. Keep Polymarket as a configurable multiplier-based formula. Update `config.py` constants.
- **Files**: `arbitrage.py`, `config.py`, `tests/test_arbitrage.py`
- **Verify**: `pytest tests/test_arbitrage.py -v` then `pytest tests/test_integration.py -v`
- **Note**: The reference doc's fee formulas (Section 2) provide the correct implementations.

### 1.3 Add Order Book Depth Information

- **Why**: `fetch_current_polymarket.py:24` takes `min(price)` across all asks, ignoring size. A 1-share ask at $0.40 is misleading if you need 100 shares.
- **What**: Enrich `get_clob_price()` to return `(price, size_at_best)` or the full asks list. Add depth fields to the API response. Display depth in CLI output.
- **Files**: `fetch_current_polymarket.py`, `api.py`, `arbitrage_bot.py`, `conftest.py`, multiple test files
- **Verify**: `pytest tests/ -m "not live" -v`
- **Note**: This is informational enrichment — it does not change core detection logic. Users can judge opportunity quality from the reported depth.

---

## Phase 2: Execution Foundation

> **Prerequisite**: Phase 1 complete. Requires API keys for both platforms.
> **Scope change**: Bot transitions from read-only to active trading.
> **Reference**: Implementation Reference Sections 4–6.

### 2.1 Kalshi Demo Environment

- [ ] Implement RSA-PSS authentication (Reference Section 5.2)
- [ ] Implement order placement: limit + IOC (Reference Section 5.3)
- [ ] Test against Kalshi demo API (`demo-api.kalshi.co`)
- [ ] Verify order lifecycle: place, fill, cancel

### 2.2 Polymarket SDK Integration

- [ ] Install `py-clob-client` SDK
- [ ] Implement authentication (private key + API creds derivation)
- [ ] Implement FOK (taker) and GTC (maker) order placement
- [ ] Test order placement on Polygon testnet or small positions

### 2.3 Cross-Platform Execution Engine

- [ ] Build parallel execution framework (`asyncio.gather` for both legs)
- [ ] Implement rollback logic for partial fills (one leg fills, other doesn't)
- [ ] Implement maker-first strategy: GTC on Polymarket, then IOC on Kalshi on fill
- [ ] Add `Decimal` for all financial calculations (required for real money)
- [ ] Fetch Polymarket fee rate dynamically via `GET /fee-rate?token_id=...`

### 2.4 New Dependencies

- `py-clob-client` — Polymarket CLOB SDK
- `cryptography` — Kalshi RSA-PSS signing
- `decimal` (stdlib) — Precision financial math

---

## Phase 3: Real-Time Streaming

> **Prerequisite**: Phase 2 complete (execution exists to act on real-time signals).
> **Reference**: Implementation Reference Section 8.

- [ ] Add Polymarket WebSocket (`wss://ws-subscriptions-clob.polymarket.com/ws/market`)
- [ ] Add Kalshi WebSocket (`wss://api.elections.kalshi.com/trade-api/ws/v2`)
- [ ] Maintain local order book state from delta updates
- [ ] Implement keepalive/heartbeat for both connections
- [ ] Subscribe to user channels for fill notifications
- [ ] Replace polling loop with event-driven detection (target: 50ms scan interval)

### New Dependencies

- `websockets` — WebSocket client library

---

## Phase 4: Risk Management and Position Tracking

> **Prerequisite**: Phase 2 complete (execution exists to manage).
> **Reference**: Implementation Reference Sections 9–10.

- [ ] Position tracking across both platforms
- [ ] Per-trade limits (2–5% of bankroll, quarter-Kelly sizing)
- [ ] Per-market and daily exposure limits
- [ ] Circuit breakers: -5% daily P&L reduces size, -10% halts trading, -15% full stop
- [ ] WebSocket disconnect detection: cancel all open orders after 5s
- [ ] API error rate monitoring: pause on >20% errors in 1 minute
- [ ] Polymarket heartbeat kill switch implementation
- [ ] P&L tracking and structured trade logging (timestamp, platform, ticker, side, qty, price, fees, P&L)

---

## Phase 5: Production Deployment

> **Prerequisite**: Phases 2–4 complete and validated.
> **Reference**: Implementation Reference Sections 13–14.

- [ ] Deploy to US East VPS with systemd/Docker process supervision
- [ ] Set up dedicated Polygon RPC node (Alchemy/QuickNode)
- [ ] Configure Prometheus + Grafana monitoring
- [ ] Set up alerting (PagerDuty for critical, Slack for warnings)
- [ ] Secure key storage (HashiCorp Vault or AWS Secrets Manager)
- [ ] IP-whitelist API access, restrict Kalshi key to trading-only
- [ ] Start with small positions ($10–50 per trade)
- [ ] Validate resolution criteria alignment on live market pairs
- [ ] Gradually increase position sizes based on performance data

---

## Reference Notes (No Code Action)

### Resolution Divergence (Section 11)

Polymarket settles on Binance BTC/USDT candle data; Kalshi settles on CF Benchmarks Real-Time Index. These can diverge during volatile periods. A 2024 Government Shutdown event saw Polymarket resolve YES while Kalshi resolved NO. For execution, maintain a **whitelist of verified market pairs** — never auto-detect. Verify settlement criteria match before trading any pair.

### Regulatory Landscape (Section 12)

Both platforms are CFTC-regulated (Kalshi since 2020, Polymarket via QCEX since July 2025). Cross-platform arbitrage is permitted. Monitor the "Prediction Markets Are Gambling Act" (Senators Schiff & Curtis, March 2026). Tax treatment is ambiguous — Section 1256 (60/40 split) is the most favorable interpretation for CFTC-regulated contracts. Log all trades with full details, retain 7 years.

---

## Phase Dependencies

```
Phase 1 (Detection Fixes)
    └── Phase 2 (Execution Foundation)
            ├── Phase 3 (WebSocket Streaming)
            └── Phase 4 (Risk Management)
                    └── Phase 5 (Production Deployment)
```

Phases 3 and 4 can proceed in parallel once Phase 2 is complete.
