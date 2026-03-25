import datetime
import pytz
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from fetch_current_polymarket import (
    get_clob_price,
    get_polymarket_data,
    fetch_polymarket_data_struct,
)
from binance import get_binance_current_price, get_binance_open_price

UTC = pytz.utc


# --- get_clob_price tests ---

class TestGetClobPrice:
    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_normal_orderbook(self, mock_fetch, sample_clob_response):
        mock_fetch.return_value = sample_clob_response
        price, size = await get_clob_price(AsyncMock(), "token123")
        assert price == Decimal("0.47")
        assert size == Decimal("150")

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_empty_asks(self, mock_fetch, sample_clob_response_empty_asks):
        mock_fetch.return_value = sample_clob_response_empty_asks
        price, size = await get_clob_price(AsyncMock(), "token123")
        assert price == Decimal("0")
        assert size == Decimal("0")

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_empty_bids_and_asks(self, mock_fetch, sample_clob_response_empty_both):
        mock_fetch.return_value = sample_clob_response_empty_both
        price, size = await get_clob_price(AsyncMock(), "token123")
        assert price == Decimal("0")
        assert size == Decimal("0")

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_multiple_asks_returns_lowest(self, mock_fetch):
        mock_fetch.return_value = {
            "bids": [],
            "asks": [{"price": "0.60", "size": "10"}, {"price": "0.55", "size": "20"}, {"price": "0.58", "size": "5"}]
        }
        price, size = await get_clob_price(AsyncMock(), "token123")
        assert price == Decimal("0.55")
        assert size == Decimal("20")

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_http_error_returns_none(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection error")
        price, size = await get_clob_price(AsyncMock(), "token123")
        assert price is None
        assert size is None

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_timeout_returns_none(self, mock_fetch):
        import asyncio
        mock_fetch.side_effect = asyncio.TimeoutError()
        price, size = await get_clob_price(AsyncMock(), "token123")
        assert price is None
        assert size is None


# --- get_polymarket_data tests ---

class TestGetPolymarketData:
    @patch('fetch_current_polymarket.get_clob_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_normal_flow(self, mock_fetch, mock_clob, sample_poly_event_response):
        mock_fetch.return_value = sample_poly_event_response
        mock_clob.side_effect = [(0.55, 100.0), (0.47, 200.0)]

        result, err = await get_polymarket_data(AsyncMock(), "bitcoin-up-or-down-test")
        assert err is None
        assert result["prices"]["Up"] == 0.55
        assert result["prices"]["Down"] == 0.47
        assert result["depth"]["Up"] == 100.0
        assert result["depth"]["Down"] == 200.0

    @patch('fetch_current_polymarket.get_clob_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_reversed_outcomes(self, mock_fetch, mock_clob, sample_poly_event_response_reversed_outcomes):
        mock_fetch.return_value = sample_poly_event_response_reversed_outcomes
        mock_clob.side_effect = [(0.47, 200.0), (0.55, 100.0)]

        result, err = await get_polymarket_data(AsyncMock(), "test")
        assert err is None
        assert result["prices"]["Down"] == 0.47
        assert result["prices"]["Up"] == 0.55

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_event_not_found(self, mock_fetch):
        mock_fetch.return_value = []
        prices, err = await get_polymarket_data(AsyncMock(), "nonexistent")
        assert prices is None
        assert "Event not found" in err

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_no_markets_in_event(self, mock_fetch):
        mock_fetch.return_value = [{"markets": []}]
        prices, err = await get_polymarket_data(AsyncMock(), "test")
        assert prices is None
        assert "Markets not found" in err

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_unexpected_token_count(self, mock_fetch):
        mock_fetch.return_value = [{
            "markets": [{
                "clobTokenIds": '["only_one_token"]',
                "outcomes": '["Up"]'
            }]
        }]
        prices, err = await get_polymarket_data(AsyncMock(), "test")
        assert prices is None
        assert "Unexpected number of tokens" in err

    @patch('fetch_current_polymarket.get_clob_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_clob_price_failure_returns_error(self, mock_fetch, mock_clob, sample_poly_event_response):
        mock_fetch.return_value = sample_poly_event_response
        mock_clob.return_value = (None, None)

        result, err = await get_polymarket_data(AsyncMock(), "test")
        assert result is None
        assert "Failed to fetch CLOB price" in err

    @patch('fetch_current_polymarket.fetch_json', new_callable=AsyncMock)
    async def test_http_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection refused")
        prices, err = await get_polymarket_data(AsyncMock(), "test")
        assert prices is None
        assert "Connection refused" in err


# --- get_binance_current_price tests ---

class TestGetBinanceCurrentPrice:
    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_success(self, mock_fetch, sample_binance_price_response):
        mock_fetch.return_value = sample_binance_price_response
        price, err = await get_binance_current_price(AsyncMock())
        assert price == Decimal("95500.00")
        assert err is None

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("Timeout")
        price, err = await get_binance_current_price(AsyncMock())
        assert price is None
        assert err is not None


# --- get_binance_open_price tests ---

class TestGetBinanceOpenPrice:
    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_success(self, mock_fetch, sample_binance_kline_response):
        mock_fetch.return_value = sample_binance_kline_response
        t = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        price, err = await get_binance_open_price(AsyncMock(), t)
        assert price == Decimal("95000.00")
        assert err is None

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_empty_kline(self, mock_fetch):
        mock_fetch.return_value = []
        t = datetime.datetime(2099, 12, 1, 14, 0, 0, tzinfo=UTC)
        price, err = await get_binance_open_price(AsyncMock(), t)
        assert price is None
        assert "Candle not found" in err

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_http_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("Timeout")
        t = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        price, err = await get_binance_open_price(AsyncMock(), t)
        assert price is None
        assert err is not None


# --- fetch_polymarket_data_struct tests ---

class TestFetchPolymarketDataStruct:
    @patch('fetch_current_polymarket.get_binance_open_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_polymarket_data', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_current_market_urls')
    async def test_normal_flow(self, mock_urls, mock_poly, mock_curr, mock_open):
        mock_urls.return_value = {
            "polymarket": "https://polymarket.com/event/bitcoin-up-or-down-december-1-2pm-et",
            "kalshi": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 19, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 14, 0, 0),
        }
        mock_poly.return_value = ({"prices": {"Up": 0.55, "Down": 0.47}, "depth": {"Up": 100.0, "Down": 200.0}}, None)
        mock_curr.return_value = (95500.0, None)
        mock_open.return_value = (95000.0, None)

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_polymarket_data_struct(session)
        assert err is None
        assert data["price_to_beat"] == 95000.0
        assert data["current_price"] == 95500.0
        assert data["prices"]["Up"] == 0.55
        assert data["prices"]["Down"] == 0.47
        assert data["depth"]["Up"] == 100.0
        assert data["depth"]["Down"] == 200.0
        assert data["slug"] == "bitcoin-up-or-down-december-1-2pm-et"

    @patch('fetch_current_polymarket.get_binance_open_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_polymarket_data', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_current_market_urls')
    async def test_polymarket_error(self, mock_urls, mock_poly, mock_curr, mock_open):
        mock_urls.return_value = {
            "polymarket": "https://polymarket.com/event/test",
            "kalshi": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 19, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 14, 0, 0),
        }
        mock_poly.return_value = (None, "Event not found")
        mock_curr.return_value = (95500.0, None)
        mock_open.return_value = (95000.0, None)

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_polymarket_data_struct(session)
        assert data is None
        assert "Polymarket Error" in err

    @patch('fetch_current_polymarket.get_binance_open_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_polymarket_data', new_callable=AsyncMock)
    @patch('fetch_current_polymarket.get_current_market_urls')
    async def test_binance_errors_still_returns_data(self, mock_urls, mock_poly, mock_curr, mock_open):
        mock_urls.return_value = {
            "polymarket": "https://polymarket.com/event/test",
            "kalshi": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 19, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 14, 0, 0),
        }
        mock_poly.return_value = ({"prices": {"Up": 0.55, "Down": 0.47}, "depth": {"Up": 100.0, "Down": 200.0}}, None)
        mock_curr.return_value = (None, "Binance error")
        mock_open.return_value = (None, "Candle not found")

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_polymarket_data_struct(session)
        assert err is None
        assert data["current_price"] is None
        assert data["price_to_beat"] is None
        assert data["prices"]["Up"] == 0.55
