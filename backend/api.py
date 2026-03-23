"""FastAPI server for the arbitrage bot.

Exposes GET /arbitrage (main endpoint) and GET /health (SEC-015).
Uses async parallel fetching for Polymarket + Kalshi data (SEC-003).
Includes server-side caching (SEC-006) and CORS restriction (SEC-004).
"""
import asyncio
import datetime
import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct
from arbitrage import estimate_fees, add_fee_info, run_arbitrage_checks
from http_utils import create_session
from config import (
    CORS_ORIGINS, PRICE_SUM_MIN, PRICE_SUM_MAX, CACHE_TTL,
    POLYMARKET_FEE_RATE, KALSHI_FEE_RATE,
)
from log_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI()

# SEC-004: Restrict CORS to configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Server-side response cache (SEC-006) ---
_cache = {"data": None, "timestamp": 0.0}


# --- Legacy aliases for backward compatibility with tests ---
_estimate_fees = estimate_fees
_add_fee_info = add_fee_info


@app.get("/arbitrage")
async def get_arbitrage_data():
    # SEC-006: return cached response if fresh enough
    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["data"]

    scan_id = str(uuid.uuid4())[:8]
    logger.info("Scan %s started", scan_id)

    # SEC-003: parallel fetching
    session = await create_session()
    try:
        poly_task = fetch_polymarket_data_struct(session)
        kalshi_task = fetch_kalshi_data_struct(session)
        (poly_data, poly_err), (kalshi_data, kalshi_err) = await asyncio.gather(
            poly_task, kalshi_task
        )
    finally:
        await session.close()

    response = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "scan_id": scan_id,
        "polymarket": poly_data,
        "kalshi": kalshi_data,
        "checks": [],
        "opportunities": [],
        "errors": [],
        "fee_disclaimer": "Fee estimates are approximate. Actual fees vary by platform, trade size, and account tier.",
    }

    if poly_err:
        response["errors"].append(poly_err)
    if kalshi_err:
        response["errors"].append(kalshi_err)

    if not poly_data or not kalshi_data:
        logger.warning("Scan %s: missing data (poly_err=%s, kalshi_err=%s)", scan_id, poly_err, kalshi_err)
        _cache["data"] = response
        _cache["timestamp"] = now
        return response

    poly_strike = poly_data["price_to_beat"]
    poly_up_cost = poly_data["prices"].get("Up", 0.0)
    poly_down_cost = poly_data["prices"].get("Down", 0.0)

    if poly_strike is None:
        response["errors"].append("Polymarket Strike is None")
        _cache["data"] = response
        _cache["timestamp"] = now
        return response

    # Sanity check: Up + Down should be approximately $1.00
    poly_sum = poly_up_cost + poly_down_cost
    if poly_sum > 0 and (poly_sum < PRICE_SUM_MIN or poly_sum > PRICE_SUM_MAX):
        response["errors"].append(
            f"Polymarket price sanity check failed: Up ({poly_up_cost:.3f}) + Down ({poly_down_cost:.3f}) = {poly_sum:.3f}, expected ~1.00"
        )
        _cache["data"] = response
        _cache["timestamp"] = now
        return response

    kalshi_markets = kalshi_data.get("markets", [])
    kalshi_markets.sort(key=lambda x: x["strike"])

    # Select ±4 window around closest Kalshi strike to poly_strike
    closest_idx = 0
    min_diff = float("inf")
    for i, m in enumerate(kalshi_markets):
        diff = abs(m["strike"] - poly_strike)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i

    start_idx = max(0, closest_idx - 4)
    end_idx = min(len(kalshi_markets), closest_idx + 5)
    selected_markets = kalshi_markets[start_idx:end_idx]

    checks, opportunities = run_arbitrage_checks(
        poly_strike, poly_up_cost, poly_down_cost, selected_markets
    )
    response["checks"] = checks
    response["opportunities"] = opportunities

    if opportunities:
        logger.info("Scan %s: %d opportunities found", scan_id, len(opportunities))
    else:
        logger.debug("Scan %s: no arbitrage found", scan_id)

    _cache["data"] = response
    _cache["timestamp"] = now
    return response


@app.get("/health")
async def health_check():
    """SEC-015: Health check endpoint for VPS monitoring."""
    import aiohttp
    from config import POLYMARKET_GAMMA_URL, KALSHI_API_URL, BINANCE_PRICE_URL

    results = {}
    timeout = aiohttp.ClientTimeout(total=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, url in [
            ("polymarket", POLYMARKET_GAMMA_URL),
            ("kalshi", KALSHI_API_URL),
            ("binance", BINANCE_PRICE_URL),
        ]:
            try:
                async with session.get(url) as resp:
                    results[name] = {"status": "ok", "http_code": resp.status}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

    all_ok = all(r["status"] == "ok" for r in results.values())
    return {"status": "healthy" if all_ok else "degraded", "services": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
