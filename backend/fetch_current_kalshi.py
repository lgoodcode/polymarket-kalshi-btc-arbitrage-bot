"""Fetch current Kalshi market data (async).

Retrieves BTC event markets from the Kalshi API and current price from Binance.
"""
import re
import logging
from decimal import Decimal
import aiohttp
from get_current_markets import get_current_market_urls
from http_utils import fetch_json, create_session
from binance import get_binance_current_price
from config import KALSHI_API_URL

logger = logging.getLogger(__name__)


async def get_kalshi_markets(session: aiohttp.ClientSession, event_ticker: str):
    """Fetch Kalshi markets for an event ticker. Returns (markets_list, error)."""
    try:
        params = {"limit": 100, "event_ticker": event_ticker}
        data = await fetch_json(session, KALSHI_API_URL, params=params)
        return data.get("markets", []), None
    except Exception as e:
        return None, str(e)


def parse_strike(subtitle: str):
    """
    Extract strike price from a Kalshi subtitle like "$96,250 or above".

    Returns Decimal or None. Logs a warning when parsing fails (SEC-013).
    """
    match = re.search(r'\$([\d,]+)', subtitle)
    if match:
        return Decimal(match.group(1).replace(",", ""))
    logger.warning("Failed to parse strike from subtitle: %r", subtitle)
    return None


async def fetch_kalshi_data_struct(session: aiohttp.ClientSession = None, binance_price=None):
    """
    Fetch current Kalshi markets. Returns (data_dict, error_string).

    Args:
        binance_price: Optional pre-fetched (price, error) tuple to avoid
            duplicate Binance API calls when called alongside fetch_polymarket_data_struct.
    """
    own_session = session is None
    if own_session:
        session = await create_session()
    try:
        market_info = get_current_market_urls()
        kalshi_url = market_info["kalshi"]
        event_ticker = kalshi_url.split("/")[-1].upper()

        if binance_price is not None:
            current_price, _ = binance_price
        else:
            current_price, _ = await get_binance_current_price(session)

        markets, err = await get_kalshi_markets(session, event_ticker)
        if err:
            return None, f"Kalshi Error: {err}"

        if not markets:
            return {"event_ticker": event_ticker, "current_price": current_price, "markets": []}, None

        market_data = []
        for m in markets:
            strike = parse_strike(m.get("subtitle", ""))
            if strike is not None and strike > 0:
                # Kalshi API returns *_dollars fields as strings
                yes_bid = Decimal(m.get("yes_bid_dollars", "0"))
                yes_ask = Decimal(m.get("yes_ask_dollars", "0"))
                no_bid = Decimal(m.get("no_bid_dollars", "0"))
                no_ask = Decimal(m.get("no_ask_dollars", "0"))
                market_data.append({
                    "strike": strike,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "subtitle": m.get("subtitle"),
                })

        market_data.sort(key=lambda x: x["strike"])

        return {
            "event_ticker": event_ticker,
            "current_price": current_price,
            "markets": market_data,
        }, None

    except Exception as e:
        return None, str(e)
    finally:
        if own_session:
            await session.close()


async def main():
    data, err = await fetch_kalshi_data_struct()

    if err:
        print(f"Error: {err}")
        return

    print(f"Fetching data for Event: {data['event_ticker']}")
    if data["current_price"]:
        print(f"CURRENT PRICE: ${data['current_price']:,.2f}")

    market_data = data["markets"]
    if not market_data:
        print("No markets found.")
        return

    current_price = data["current_price"] or 0
    closest_idx = 0
    min_diff = float("inf")
    for i, m in enumerate(market_data):
        diff = abs(m["strike"] - current_price)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i

    start_idx = max(0, closest_idx - 1)
    end_idx = min(len(market_data), start_idx + 3)
    if end_idx - start_idx < 3 and start_idx > 0:
        start_idx = max(0, end_idx - 3)

    selected_markets = market_data[start_idx:end_idx]

    print("-" * 30)
    for i, m in enumerate(selected_markets):
        print(f"PRICE TO BEAT {i + 1}: {m['subtitle']}")
        print(f"BUY YES PRICE {i + 1}: ${m['yes_ask']:.2f}, BUY NO PRICE {i + 1}: ${m['no_ask']:.2f}")
        print()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
