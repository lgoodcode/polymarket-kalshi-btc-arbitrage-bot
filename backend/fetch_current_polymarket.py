"""Fetch current Polymarket data (async).

Retrieves event metadata from the Gamma API, order book prices from CLOB,
and BTC prices from Binance.
"""
import json
import logging
import aiohttp
from get_current_markets import get_current_market_urls
from http_utils import fetch_json, create_session
from binance import get_binance_current_price, get_binance_open_price
from config import POLYMARKET_GAMMA_URL, POLYMARKET_CLOB_URL

logger = logging.getLogger(__name__)


async def get_clob_price(session: aiohttp.ClientSession, token_id: str):
    """Fetch best ask from the Polymarket CLOB order book.

    Returns (price, size) tuple. Returns (None, None) on error,
    (0.0, 0.0) when no asks are available.
    """
    try:
        data = await fetch_json(session, POLYMARKET_CLOB_URL, params={"token_id": token_id})

        asks = data.get("asks", [])
        if asks:
            best = min(asks, key=lambda a: float(a["price"]))
            price = float(best["price"])
            size = float(best.get("size", "0"))
            return (price, size) if price > 0 else (0.0, 0.0)
        return (0.0, 0.0)
    except Exception as e:
        logger.error("CLOB price fetch failed for token %s: %s", token_id, e)
        return (None, None)


async def get_polymarket_data(session: aiohttp.ClientSession, slug: str):
    """Fetch Polymarket event details and CLOB prices. Returns (prices_dict, error)."""
    try:
        data = await fetch_json(session, POLYMARKET_GAMMA_URL, params={"slug": slug})

        if not data:
            return None, "Event not found"

        event = data[0]
        markets = event.get("markets", [])
        if not markets:
            return None, "Markets not found in event"

        market = markets[0]
        clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))
        outcomes = json.loads(market.get("outcomes", "[]"))

        if len(clob_token_ids) != 2:
            return None, "Unexpected number of tokens"

        if len(outcomes) != len(clob_token_ids):
            return None, f"Mismatched outcomes ({len(outcomes)}) and token IDs ({len(clob_token_ids)})"

        prices = {}
        depth = {}
        for outcome, token_id in zip(outcomes, clob_token_ids):
            price, size = await get_clob_price(session, token_id)
            if price is not None:
                prices[outcome] = price
                depth[outcome] = size
            else:
                return None, f"Failed to fetch CLOB price for {outcome} (token: {token_id})"

        return {"prices": prices, "depth": depth}, None
    except Exception as e:
        return None, str(e)


async def fetch_polymarket_data_struct(session: aiohttp.ClientSession = None, binance_price=None):
    """
    Fetch current Polymarket data. Returns (data_dict, error_string).

    If price_to_beat or current_price cannot be fetched from Binance,
    they are set to None with a warning logged. The caller (api.py)
    is responsible for checking None values before using them (SEC-007).

    Args:
        binance_price: Optional pre-fetched (price, error) tuple to avoid
            duplicate Binance API calls when called alongside fetch_kalshi_data_struct.
    """
    own_session = session is None
    if own_session:
        session = await create_session()
    try:
        market_info = get_current_market_urls()
        polymarket_url = market_info["polymarket"]
        target_time_utc = market_info["target_time_utc"]
        slug = polymarket_url.split("/")[-1]

        poly_result, poly_err = await get_polymarket_data(session, slug)
        if poly_err:
            return None, f"Polymarket Error: {poly_err}"

        if binance_price is not None:
            current_price, curr_err = binance_price
        else:
            current_price, curr_err = await get_binance_current_price(session)
        price_to_beat, beat_err = await get_binance_open_price(session, target_time_utc)

        # SEC-007: treat None critical prices as error
        if price_to_beat is None:
            logger.warning("price_to_beat is None: %s", beat_err)
        if current_price is None:
            logger.warning("current_price is None: %s", curr_err)

        return {
            "price_to_beat": price_to_beat,
            "current_price": current_price,
            "prices": poly_result["prices"],
            "depth": poly_result["depth"],
            "slug": slug,
            "target_time_utc": target_time_utc,
        }, None

    except Exception as e:
        return None, str(e)
    finally:
        if own_session:
            await session.close()


async def main():
    data, err = await fetch_polymarket_data_struct()

    if err:
        print(f"Error: {err}")
        return

    print(f"Fetching data for: {data['slug']}")
    print(f"Target Time (UTC): {data['target_time_utc']}")
    print("-" * 50)

    if data["price_to_beat"] is None:
        print("PRICE TO BEAT: Error")
    else:
        print(f"PRICE TO BEAT: ${data['price_to_beat']:,.2f}")

    if data["current_price"] is None:
        print("CURRENT PRICE: Error")
    else:
        print(f"CURRENT PRICE: ${data['current_price']:,.2f}")

    up_price = data["prices"].get("Up", 0)
    down_price = data["prices"].get("Down", 0)
    up_depth = data["depth"].get("Up", 0)
    down_depth = data["depth"].get("Down", 0)
    print(f"BUY: UP ${up_price:.3f} ({up_depth:.0f} avail) & DOWN ${down_price:.3f} ({down_depth:.0f} avail)")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
