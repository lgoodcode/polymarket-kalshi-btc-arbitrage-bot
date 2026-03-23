# Bot Usage Guide

## What This Bot Does

This bot detects **risk-free arbitrage opportunities** between Bitcoin hourly prediction markets on **Polymarket** and **Kalshi**. It monitors both platforms and identifies when you can buy complementary contracts across platforms for less than $1.00 combined, guaranteeing a minimum $1.00 payout regardless of outcome.

**The bot is read-only** — it detects opportunities but does not execute trades.

## Prerequisites

- **Python 3.9+**
- **Node.js 18+** and npm (only needed for the frontend dashboard)
- No API keys or accounts required (all endpoints are public)

## Installation

```bash
# Backend
cd backend
pip install -r requirements.txt

# Frontend (optional)
cd frontend
npm install
```

## Running the Bot

### Option 1: API Server

Starts a FastAPI server that returns arbitrage data as JSON.

```bash
cd backend
python api.py
```

- Serves at `http://localhost:8000`
- Single endpoint: `GET /arbitrage`
- Returns JSON with market data, arbitrage checks, opportunities, and any errors

### Option 2: CLI Bot

Runs a continuous scanner that prints findings to the console.

```bash
cd backend
python arbitrage_bot.py
```

- Polls every 1 second
- Press `Ctrl+C` to stop
- Shows Polymarket prices, Kalshi markets, and any arbitrage found

### Option 3: Frontend Dashboard

A real-time visual dashboard that polls the API server.

```bash
# Terminal 1: Start the API server
cd backend
python api.py

# Terminal 2: Start the frontend
cd frontend
npm run dev
```

- Dashboard at `http://localhost:3000`
- Auto-refreshes every 1 second
- Highlights the best opportunity with the highest margin

## Understanding the Output

### Arbitrage Detection

The bot compares **Polymarket's strike price** against each **Kalshi strike price**:

| Scenario | Strategy | Guaranteed Payout |
|----------|----------|-------------------|
| Poly Strike > Kalshi Strike | Buy Poly DOWN + Kalshi YES | $1.00 minimum |
| Poly Strike < Kalshi Strike | Buy Poly UP + Kalshi NO | $1.00 minimum |
| Poly Strike = Kalshi Strike | Check both combinations | $1.00 minimum |

An arbitrage exists when `total_cost < $1.00`. The **margin** is `$1.00 - total_cost`.

### Fee Impact

Fees reduce the effective margin:
- **Polymarket**: ~2% on winnings (`(1.00 - cost) × 0.02`)
- **Kalshi**: ~7% on profits (`(1.00 - cost) × 0.07`)

The bot calculates `margin_after_fees` and reports whether the opportunity is still **PROFITABLE** after fees.

### Safety Checks

- **Price sanity check**: If Polymarket Up + Down is outside the range [0.85, 1.15], prices may be stale
- **Unpriced markets**: Kalshi markets with $0 ask prices are skipped
- **Error handling**: API failures are reported in the `errors` array without crashing

## Running Tests

```bash
cd backend

# Run all unit tests (fast, no network needed)
pytest tests/ -m "not integration and not live" -v

# Run integration tests (full pipeline with mocked HTTP)
pytest tests/ -m integration -v

# Run all offline tests (unit + integration)
pytest tests/ -m "not live" -v

# Run live smoke tests (requires network access)
RUN_LIVE_TESTS=1 pytest tests/ -m live -v

# Run everything
RUN_LIVE_TESTS=1 pytest tests/ -v
```

## API Endpoints Used

| API | Endpoint | Auth | Purpose |
|-----|----------|------|---------|
| Polymarket Gamma | `GET /events?slug=` | None | Market metadata, token IDs |
| Polymarket CLOB | `GET /book?token_id=` | None | Order book (bid/ask prices) |
| Kalshi Trade v2 | `GET /markets?event_ticker=` | None | Market list with strike prices |
| Binance Spot v3 | `GET /ticker/price` | None | Current BTC price |
| Binance Spot v3 | `GET /klines` | None | Hourly open price (strike) |

## Market Timing

- Markets are hourly, based on **Eastern Time (ET)**
- Polymarket uses the current hour; Kalshi uses the next hour's identifier
- The bot automatically generates the correct market slugs/tickers for the current time
- Markets are most active during US trading hours
