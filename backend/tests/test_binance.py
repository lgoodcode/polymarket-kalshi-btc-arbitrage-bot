import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from binance import get_binance_current_price, get_binance_open_price


class TestGetBinanceCurrentPrice:
    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_success(self, mock_fetch, sample_binance_price_response):
        mock_fetch.return_value = sample_binance_price_response
        price, err = await get_binance_current_price(AsyncMock())
        assert price == 95500.0
        assert err is None

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_http_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection error")
        price, err = await get_binance_current_price(AsyncMock())
        assert price is None
        assert "Connection error" in err

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_timeout(self, mock_fetch):
        mock_fetch.side_effect = asyncio.TimeoutError("Timeout")
        price, err = await get_binance_current_price(AsyncMock())
        assert price is None
        assert err is not None


class TestGetBinanceOpenPrice:
    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_success(self, mock_fetch, sample_binance_kline_response):
        import datetime
        import pytz
        mock_fetch.return_value = sample_binance_kline_response
        target = datetime.datetime(2026, 3, 23, 14, 0, 0, tzinfo=pytz.utc)
        price, err = await get_binance_open_price(AsyncMock(), target)
        assert price == 95000.0
        assert err is None

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_empty_response(self, mock_fetch):
        import datetime
        import pytz
        mock_fetch.return_value = []
        target = datetime.datetime(2026, 3, 23, 14, 0, 0, tzinfo=pytz.utc)
        price, err = await get_binance_open_price(AsyncMock(), target)
        assert price is None
        assert "not found" in err

    @patch('binance.fetch_json', new_callable=AsyncMock)
    async def test_http_error(self, mock_fetch):
        import datetime
        import pytz
        mock_fetch.side_effect = Exception("API Error")
        target = datetime.datetime(2026, 3, 23, 14, 0, 0, tzinfo=pytz.utc)
        price, err = await get_binance_open_price(AsyncMock(), target)
        assert price is None
        assert "API Error" in err
