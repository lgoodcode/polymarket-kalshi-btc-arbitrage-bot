import datetime
import pytz
import pytest
from unittest.mock import patch, MagicMock

from fetch_current_polymarket import (
    get_clob_price,
    get_polymarket_data,
    get_binance_current_price,
    get_binance_open_price,
    fetch_polymarket_data_struct,
)

UTC = pytz.utc


# --- get_clob_price tests ---

class TestGetClobPrice:
    @patch('fetch_current_polymarket.requests.get')
    def test_normal_orderbook(self, mock_get, sample_clob_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_clob_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        price = get_clob_price("token123")
        assert price == 0.47  # min of asks

    @patch('fetch_current_polymarket.requests.get')
    def test_empty_asks(self, mock_get, sample_clob_response_empty_asks):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_clob_response_empty_asks
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        price = get_clob_price("token123")
        assert price == 0.0  # No asks → 0.0

    @patch('fetch_current_polymarket.requests.get')
    def test_empty_bids_and_asks(self, mock_get, sample_clob_response_empty_both):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_clob_response_empty_both
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        price = get_clob_price("token123")
        assert price == 0.0

    @patch('fetch_current_polymarket.requests.get')
    def test_multiple_asks_returns_lowest(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "bids": [],
            "asks": [{"price": "0.60", "size": "10"}, {"price": "0.55", "size": "20"}, {"price": "0.58", "size": "5"}]
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        price = get_clob_price("token123")
        assert price == 0.55

    @patch('fetch_current_polymarket.requests.get')
    def test_http_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        price = get_clob_price("token123")
        assert price is None

    @patch('fetch_current_polymarket.requests.get')
    def test_timeout_returns_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()
        price = get_clob_price("token123")
        assert price is None

    @patch('fetch_current_polymarket.requests.get')
    def test_uses_timeout_param(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"bids": [], "asks": []}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        get_clob_price("token123")
        _, kwargs = mock_get.call_args
        assert kwargs.get('timeout') == 10


# --- get_polymarket_data tests ---

class TestGetPolymarketData:
    @patch('fetch_current_polymarket.get_clob_price')
    @patch('fetch_current_polymarket.requests.get')
    def test_normal_flow(self, mock_get, mock_clob, sample_poly_event_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_poly_event_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        mock_clob.side_effect = [0.55, 0.47]  # Up, Down

        prices, err = get_polymarket_data("bitcoin-up-or-down-test")
        assert err is None
        assert prices["Up"] == 0.55
        assert prices["Down"] == 0.47

    @patch('fetch_current_polymarket.get_clob_price')
    @patch('fetch_current_polymarket.requests.get')
    def test_reversed_outcomes(self, mock_get, mock_clob, sample_poly_event_response_reversed_outcomes):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_poly_event_response_reversed_outcomes
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        mock_clob.side_effect = [0.47, 0.55]  # Down, Up (reversed order)

        prices, err = get_polymarket_data("test")
        assert err is None
        assert prices["Down"] == 0.47
        assert prices["Up"] == 0.55

    @patch('fetch_current_polymarket.requests.get')
    def test_event_not_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        prices, err = get_polymarket_data("nonexistent")
        assert prices is None
        assert "Event not found" in err

    @patch('fetch_current_polymarket.requests.get')
    def test_no_markets_in_event(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"markets": []}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        prices, err = get_polymarket_data("test")
        assert prices is None
        assert "Markets not found" in err

    @patch('fetch_current_polymarket.requests.get')
    def test_unexpected_token_count(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{
            "markets": [{
                "clobTokenIds": '["only_one_token"]',
                "outcomes": '["Up"]'
            }]
        }]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        prices, err = get_polymarket_data("test")
        assert prices is None
        assert "Unexpected number of tokens" in err

    @patch('fetch_current_polymarket.get_clob_price')
    @patch('fetch_current_polymarket.requests.get')
    def test_clob_price_failure_returns_error(self, mock_get, mock_clob, sample_poly_event_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_poly_event_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        mock_clob.return_value = None  # CLOB failure

        prices, err = get_polymarket_data("test")
        assert prices is None
        assert "Failed to fetch CLOB price" in err

    @patch('fetch_current_polymarket.requests.get')
    def test_http_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        prices, err = get_polymarket_data("test")
        assert prices is None
        assert "Connection refused" in err


# --- get_binance_current_price tests ---

class TestGetBinanceCurrentPrice:
    @patch('fetch_current_polymarket.requests.get')
    def test_success(self, mock_get, sample_binance_price_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_binance_price_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        price, err = get_binance_current_price()
        assert price == 95500.0
        assert err is None

    @patch('fetch_current_polymarket.requests.get')
    def test_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")
        price, err = get_binance_current_price()
        assert price is None
        assert err is not None


# --- get_binance_open_price tests ---

class TestGetBinanceOpenPrice:
    @patch('fetch_current_polymarket.requests.get')
    def test_success(self, mock_get, sample_binance_kline_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_binance_kline_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        t = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        price, err = get_binance_open_price(t)
        assert price == 95000.0
        assert err is None

    @patch('fetch_current_polymarket.requests.get')
    def test_empty_kline(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        t = datetime.datetime(2099, 12, 1, 14, 0, 0, tzinfo=UTC)
        price, err = get_binance_open_price(t)
        assert price is None
        assert "Candle not found" in err

    @patch('fetch_current_polymarket.requests.get')
    def test_http_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")
        t = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        price, err = get_binance_open_price(t)
        assert price is None
        assert err is not None

    @patch('fetch_current_polymarket.requests.get')
    def test_uses_timeout(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [[0, "100.0"]]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        t = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        get_binance_open_price(t)
        _, kwargs = mock_get.call_args
        assert kwargs.get('timeout') == 10


# --- fetch_polymarket_data_struct tests ---

class TestFetchPolymarketDataStruct:
    @patch('fetch_current_polymarket.get_binance_open_price')
    @patch('fetch_current_polymarket.get_binance_current_price')
    @patch('fetch_current_polymarket.get_polymarket_data')
    @patch('fetch_current_polymarket.get_current_market_urls')
    def test_normal_flow(self, mock_urls, mock_poly, mock_curr, mock_open):
        mock_urls.return_value = {
            "polymarket": "https://polymarket.com/event/bitcoin-up-or-down-december-1-2pm-et",
            "kalshi": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 19, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 14, 0, 0),
        }
        mock_poly.return_value = ({"Up": 0.55, "Down": 0.47}, None)
        mock_curr.return_value = (95500.0, None)
        mock_open.return_value = (95000.0, None)

        data, err = fetch_polymarket_data_struct()
        assert err is None
        assert data["price_to_beat"] == 95000.0
        assert data["current_price"] == 95500.0
        assert data["prices"]["Up"] == 0.55
        assert data["prices"]["Down"] == 0.47
        assert data["slug"] == "bitcoin-up-or-down-december-1-2pm-et"

    @patch('fetch_current_polymarket.get_binance_open_price')
    @patch('fetch_current_polymarket.get_binance_current_price')
    @patch('fetch_current_polymarket.get_polymarket_data')
    @patch('fetch_current_polymarket.get_current_market_urls')
    def test_polymarket_error(self, mock_urls, mock_poly, mock_curr, mock_open):
        mock_urls.return_value = {
            "polymarket": "https://polymarket.com/event/test",
            "kalshi": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 19, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 14, 0, 0),
        }
        mock_poly.return_value = (None, "Event not found")
        mock_curr.return_value = (95500.0, None)
        mock_open.return_value = (95000.0, None)

        data, err = fetch_polymarket_data_struct()
        assert data is None
        assert "Polymarket Error" in err

    @patch('fetch_current_polymarket.get_binance_open_price')
    @patch('fetch_current_polymarket.get_binance_current_price')
    @patch('fetch_current_polymarket.get_polymarket_data')
    @patch('fetch_current_polymarket.get_current_market_urls')
    def test_binance_errors_still_returns_data(self, mock_urls, mock_poly, mock_curr, mock_open):
        mock_urls.return_value = {
            "polymarket": "https://polymarket.com/event/test",
            "kalshi": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 19, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 14, 0, 0),
        }
        mock_poly.return_value = ({"Up": 0.55, "Down": 0.47}, None)
        mock_curr.return_value = (None, "Binance error")
        mock_open.return_value = (None, "Candle not found")

        data, err = fetch_polymarket_data_struct()
        assert err is None
        assert data["current_price"] is None
        assert data["price_to_beat"] is None
        assert data["prices"]["Up"] == 0.55
