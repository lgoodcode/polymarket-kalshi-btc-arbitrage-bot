"""
Tier 3: Live dry-run smoke tests.

These tests hit REAL external APIs with no trading — they validate that the
full pipeline works against live production endpoints.

Run with: RUN_LIVE_TESTS=1 pytest tests/test_e2e_live.py -v

These tests are:
- Gated by RUN_LIVE_TESTS=1 environment variable
- Marked with @pytest.mark.live for easy selection/deselection
- Network errors skip gracefully (don't fail CI)
- Non-deterministic (prices change constantly)
"""
import os
import pytest
import aiohttp
import asyncio

# Skip all tests in this module if RUN_LIVE_TESTS is not set
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="Live tests disabled. Set RUN_LIVE_TESTS=1 to enable.",
    ),
]

TIMEOUT = aiohttp.ClientTimeout(total=15)


@pytest.mark.live
class TestLivePolymarketGamma:
    """Validate Polymarket Gamma API is reachable and returns expected data."""

    async def test_live_polymarket_gamma_reachable(self):
        try:
            from get_current_markets import get_current_market_urls
            urls = get_current_market_urls()
            slug = urls["polymarket"].split("/")[-1]

            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(
                    "https://gamma-api.polymarket.com/events",
                    params={"slug": slug},
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()

            assert isinstance(data, list), f"Expected list, got {type(data)}"
            if data:
                event = data[0]
                assert "markets" in event
                if event["markets"]:
                    market = event["markets"][0]
                    assert "clobTokenIds" in market
                    assert "outcomes" in market
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            pytest.skip(f"Network error: {e}")


@pytest.mark.live
class TestLivePolymarketCLOB:
    """Validate Polymarket CLOB API returns order book data."""

    async def test_live_polymarket_clob_reachable(self):
        try:
            import json as json_mod
            from get_current_markets import get_current_market_urls

            urls = get_current_market_urls()
            slug = urls["polymarket"].split("/")[-1]

            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                # First get token IDs from Gamma
                async with session.get(
                    "https://gamma-api.polymarket.com/events",
                    params={"slug": slug},
                ) as resp:
                    data = await resp.json()

                if not data or not data[0].get("markets"):
                    pytest.skip("No active market found for current hour")

                market = data[0]["markets"][0]
                token_ids = json_mod.loads(market.get("clobTokenIds", "[]"))

                if not token_ids:
                    pytest.skip("No token IDs found")

                # Fetch order book for first token
                async with session.get(
                    "https://clob.polymarket.com/book",
                    params={"token_id": token_ids[0]},
                ) as clob_resp:
                    book = await clob_resp.json()

            assert "bids" in book or "asks" in book
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            pytest.skip(f"Network error: {e}")


@pytest.mark.live
class TestLiveKalshiMarkets:
    """Validate Kalshi API returns market data."""

    async def test_live_kalshi_markets_reachable(self):
        try:
            from get_current_markets import get_current_market_urls

            urls = get_current_market_urls()
            event_ticker = urls["kalshi"].split("/")[-1].upper()

            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(
                    "https://api.elections.kalshi.com/trade-api/v2/markets",
                    params={"limit": 5, "event_ticker": event_ticker},
                ) as resp:
                    data = await resp.json()

            assert "markets" in data
            if data["markets"]:
                market = data["markets"][0]
                assert "subtitle" in market
                # Verify new dollar fields exist (post-March 2026)
                assert "yes_ask_dollars" in market or "yes_ask" in market
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            pytest.skip(f"Network error: {e}")


@pytest.mark.live
class TestLiveBinancePrice:
    """Validate Binance API returns BTC price."""

    async def test_live_binance_price_reachable(self):
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": "BTCUSDT"},
                ) as resp:
                    data = await resp.json()

            assert "price" in data
            price = float(data["price"])
            assert price > 0
            # BTC should be in a reasonable range
            assert 10000 < price < 500000, f"BTC price {price} seems unreasonable"
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            pytest.skip(f"Network error: {e}")


@pytest.mark.live
class TestLiveFullPipeline:
    """Run the full fetch pipeline against live APIs."""

    async def test_live_full_pipeline_smoke(self):
        try:
            from fetch_current_polymarket import fetch_polymarket_data_struct
            from fetch_current_kalshi import fetch_kalshi_data_struct

            poly_data, poly_err = await fetch_polymarket_data_struct()
            kalshi_data, kalshi_err = await fetch_kalshi_data_struct()

            # At least one should succeed (or both have graceful errors)
            if poly_err and kalshi_err:
                pytest.skip(f"Both APIs errored: poly={poly_err}, kalshi={kalshi_err}")

            if poly_data:
                assert "prices" in poly_data
                assert "price_to_beat" in poly_data
                assert "current_price" in poly_data

                prices = poly_data["prices"]
                if "Up" in prices and "Down" in prices:
                    up = prices["Up"]
                    down = prices["Down"]
                    if up > 0 and down > 0:
                        total = up + down
                        assert 0.70 <= total <= 1.30, f"Up+Down = {total}"

            if kalshi_data:
                assert "markets" in kalshi_data
                assert "event_ticker" in kalshi_data
                for m in kalshi_data["markets"]:
                    assert "strike" in m
                    assert "yes_ask" in m
                    assert "no_ask" in m
                    # Values should be in dollars (0-1 range)
                    assert 0 <= m["yes_ask"] <= 1.0
                    assert 0 <= m["no_ask"] <= 1.0

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            pytest.skip(f"Network error: {e}")
