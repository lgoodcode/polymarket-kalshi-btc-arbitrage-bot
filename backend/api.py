"""FastAPI server for the arbitrage bot.

Exposes GET /arbitrage (main endpoint) and GET /health (SEC-015).
Uses async parallel fetching for Polymarket + Kalshi data (SEC-003).
Includes server-side caching (SEC-006) and CORS restriction (SEC-004).
"""
import asyncio
import datetime
import json
import logging
import time
import uuid
from decimal import Decimal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from decimal_utils import decimal_to_json

from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct
from arbitrage import estimate_fees, add_fee_info, run_arbitrage_checks
from binance import get_binance_current_price
from http_utils import create_session
from config import CORS_ORIGINS, PRICE_SUM_MIN, PRICE_SUM_MAX, CACHE_TTL
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


def clear_cache():
    """Reset the server-side response cache."""
    _cache["data"] = None
    _cache["timestamp"] = 0.0


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

    # SEC-003: parallel fetching; fetch Binance price once to avoid duplicate calls
    session = await create_session()
    try:
        binance_price = await get_binance_current_price(session)
        poly_task = fetch_polymarket_data_struct(session, binance_price=binance_price)
        kalshi_task = fetch_kalshi_data_struct(session, binance_price=binance_price)
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
        response = decimal_to_json(response)
        _cache["data"] = response
        _cache["timestamp"] = now
        return response

    poly_strike = poly_data["price_to_beat"]
    poly_up_cost = poly_data["prices"].get("Up", Decimal("0"))
    poly_down_cost = poly_data["prices"].get("Down", Decimal("0"))

    if poly_strike is None:
        response["errors"].append("Polymarket Strike is None")
        response = decimal_to_json(response)
        _cache["data"] = response
        _cache["timestamp"] = now
        return response

    # Sanity check: Up + Down should be approximately $1.00
    poly_sum = poly_up_cost + poly_down_cost
    if poly_sum > 0 and (poly_sum < PRICE_SUM_MIN or poly_sum > PRICE_SUM_MAX):
        response["errors"].append(
            f"Polymarket price sanity check failed: Up ({float(poly_up_cost):.3f}) + Down ({float(poly_down_cost):.3f}) = {float(poly_sum):.3f}, expected ~1.00"
        )
        response = decimal_to_json(response)
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

    # Convert Decimal values to float for JSON serialization
    response = decimal_to_json(response)
    _cache["data"] = response
    _cache["timestamp"] = now
    return response


@app.get("/health")
async def health_check():
    """SEC-015: Health check endpoint for VPS monitoring."""
    import aiohttp
    from config import POLYMARKET_GAMMA_URL, KALSHI_API_URL, BINANCE_PRICE_URL, SYMBOL

    health_targets = [
        ("polymarket", POLYMARKET_GAMMA_URL, {"slug": "health-check"}),
        ("kalshi", KALSHI_API_URL, {"limit": "1"}),
        ("binance", BINANCE_PRICE_URL, {"symbol": SYMBOL}),
    ]

    results = {}
    timeout = aiohttp.ClientTimeout(total=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, url, params in health_targets:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status >= 400:
                        results[name] = {"status": "error", "http_code": resp.status}
                    else:
                        results[name] = {"status": "ok", "http_code": resp.status}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

    all_ok = all(r["status"] == "ok" for r in results.values())
    return {"status": "healthy" if all_ok else "degraded", "services": results}


# --- Execution endpoints ---


@app.get("/execution/status")
async def execution_status():
    """Return current execution configuration state."""
    from config import EXECUTION_ENABLED, EXECUTION_DRY_RUN, KALSHI_API_BASE_URL

    return {
        "enabled": EXECUTION_ENABLED,
        "dry_run": EXECUTION_DRY_RUN,
        "kalshi_environment": "demo" if "demo" in KALSHI_API_BASE_URL else "production",
    }


@app.post("/execute")
async def execute_arbitrage(body: dict):
    """Execute an arbitrage opportunity.

    Requires EXECUTION_ENABLED=true. Dry-run by default.

    Body: {
        "poly_token_id": str,
        "kalshi_ticker": str,
        "opportunity": dict,   # from /arbitrage response
        "size": int (optional, default from config),
        "strategy": str (optional, "maker_first" or "parallel")
    }
    """
    from config import (
        EXECUTION_ENABLED, EXECUTION_DRY_RUN, DEFAULT_ORDER_SIZE,
        KALSHI_API_BASE_URL, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH,
        POLYMARKET_HOST, POLYMARKET_PRIVATE_KEY, POLYMARKET_CHAIN_ID,
    )

    if not EXECUTION_ENABLED:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=403,
            content={"error": "Execution is disabled. Set EXECUTION_ENABLED=true to enable."},
        )

    # Validate required fields
    for field in ("poly_token_id", "kalshi_ticker", "opportunity"):
        if field not in body:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"error": f"Missing required field: {field}"},
            )

    opportunity = body["opportunity"]
    size = body.get("size", DEFAULT_ORDER_SIZE)
    strategy = body.get("strategy", "maker_first")

    # Initialize clients
    from execution.kalshi_client import KalshiClient
    from execution.polymarket_client import PolymarketClient
    from execution.engine import ExecutionEngine

    kalshi_client = KalshiClient(
        base_url=KALSHI_API_BASE_URL,
        api_key_id=KALSHI_API_KEY_ID,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
    )
    ok, err = kalshi_client.initialize()
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"error": f"Kalshi client init failed: {err}"},
        )

    poly_client = PolymarketClient(
        host=POLYMARKET_HOST,
        private_key=POLYMARKET_PRIVATE_KEY,
        chain_id=POLYMARKET_CHAIN_ID,
    )
    ok, err = poly_client.initialize()
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"error": f"Polymarket client init failed: {err}"},
        )

    engine = ExecutionEngine(poly_client, kalshi_client, dry_run=EXECUTION_DRY_RUN)
    plan = engine.build_execution_plan(
        opportunity,
        poly_token_id=body["poly_token_id"],
        kalshi_ticker=body["kalshi_ticker"],
        size=size,
        strategy=strategy,
    )

    session = await create_session()
    try:
        result = await engine.execute(session, plan)
    finally:
        await session.close()

    # Convert Decimal values for JSON serialization
    def _serialize(obj):
        if hasattr(obj, '__dataclass_fields__'):
            from dataclasses import asdict
            return asdict(obj)
        return obj

    from dataclasses import asdict
    result_dict = asdict(result)

    # Convert Decimal to float for JSON
    def _decimal_to_float(d):
        if isinstance(d, dict):
            return {k: _decimal_to_float(v) for k, v in d.items()}
        if isinstance(d, list):
            return [_decimal_to_float(v) for v in d]
        if isinstance(d, Decimal):
            return float(d)
        return d

    from decimal import Decimal
    return _decimal_to_float(result_dict)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
