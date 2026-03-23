"""Shared Binance API functions (async).

Single source of truth for BTC price fetching — used by both
fetch_current_polymarket and fetch_current_kalshi.
"""
import logging
import aiohttp
from http_utils import fetch_json
from config import BINANCE_PRICE_URL, BINANCE_KLINES_URL, SYMBOL

logger = logging.getLogger(__name__)


async def get_binance_current_price(session: aiohttp.ClientSession):
    """Fetch current BTC spot price from Binance. Returns (price, error)."""
    try:
        data = await fetch_json(session, BINANCE_PRICE_URL, params={"symbol": SYMBOL})
        return float(data["price"]), None
    except Exception as e:
        logger.error("Binance current price fetch failed: %s", e)
        return None, str(e)


async def get_binance_open_price(session: aiohttp.ClientSession, target_time_utc):
    """Fetch the 1-hour candle open price for a given UTC time. Returns (price, error)."""
    try:
        timestamp_ms = int(target_time_utc.timestamp() * 1000)
        params = {
            "symbol": SYMBOL,
            "interval": "1h",
            "startTime": timestamp_ms,
            "limit": 1,
        }
        data = await fetch_json(session, BINANCE_KLINES_URL, params=params)

        if not data:
            return None, "Candle not found yet"

        open_price = float(data[0][1])
        return open_price, None
    except Exception as e:
        logger.error("Binance open price fetch failed: %s", e)
        return None, str(e)
