import datetime
import pytz
import pytest
from unittest.mock import patch, MagicMock

from fetch_current_kalshi import (
    parse_strike,
    get_binance_current_price,
    get_kalshi_markets,
    fetch_kalshi_data_struct,
)

UTC = pytz.utc


# --- parse_strike tests ---

class TestParseStrike:
    def test_normal_strike(self):
        assert parse_strike("$96,250 or above") == 96250.0

    def test_large_strike(self):
        assert parse_strike("$100,000 or above") == 100000.0

    def test_small_strike(self):
        assert parse_strike("$500 or above") == 500.0

    def test_no_comma(self):
        assert parse_strike("$85000 or above") == 85000.0

    def test_no_dollar_sign(self):
        assert parse_strike("no dollar sign") is None

    def test_empty_string(self):
        assert parse_strike("") is None

    def test_zero_strike(self):
        # Returns 0.0 which the caller filters out
        assert parse_strike("$0 or above") == 0.0

    def test_multiple_dollar_signs(self):
        # Should match the first one
        result = parse_strike("$94,000 to $95,000")
        assert result == 94000.0


# --- get_binance_current_price tests ---

class TestGetBinanceCurrentPrice:
    @patch('fetch_current_kalshi.requests.get')
    def test_success(self, mock_get, sample_binance_price_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_binance_price_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        price, err = get_binance_current_price()
        assert price == 95500.0
        assert err is None

    @patch('fetch_current_kalshi.requests.get')
    def test_http_error(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        price, err = get_binance_current_price()
        assert price is None
        assert "Connection error" in err

    @patch('fetch_current_kalshi.requests.get')
    def test_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("Timeout")
        price, err = get_binance_current_price()
        assert price is None
        assert err is not None

    @patch('fetch_current_kalshi.requests.get')
    def test_uses_timeout_param(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"symbol": "BTCUSDT", "price": "100.0"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        get_binance_current_price()
        _, kwargs = mock_get.call_args
        assert kwargs.get('timeout') == 10


# --- get_kalshi_markets tests ---

class TestGetKalshiMarkets:
    @patch('fetch_current_kalshi.requests.get')
    def test_success(self, mock_get, sample_kalshi_api_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_kalshi_api_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        markets, err = get_kalshi_markets("KXBTCD-25NOV2614")
        assert err is None
        assert len(markets) == 3

    @patch('fetch_current_kalshi.requests.get')
    def test_empty_markets(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"markets": []}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        markets, err = get_kalshi_markets("KXBTCD-UNKNOWN")
        assert err is None
        assert markets == []

    @patch('fetch_current_kalshi.requests.get')
    def test_http_error(self, mock_get):
        mock_get.side_effect = Exception("500 Server Error")
        markets, err = get_kalshi_markets("KXBTCD-25NOV2614")
        assert markets is None
        assert "500 Server Error" in err

    @patch('fetch_current_kalshi.requests.get')
    def test_uses_timeout(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"markets": []}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        get_kalshi_markets("TEST")
        _, kwargs = mock_get.call_args
        assert kwargs.get('timeout') == 10


# --- fetch_kalshi_data_struct tests ---

class TestFetchKalshiDataStruct:
    @patch('fetch_current_kalshi.get_kalshi_markets')
    @patch('fetch_current_kalshi.get_binance_current_price')
    @patch('fetch_current_kalshi.get_current_market_urls')
    def test_normal_flow(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([
            {"subtitle": "$94,000 or above", "yes_bid": 85, "yes_ask": 87, "no_bid": 12, "no_ask": 14},
            {"subtitle": "$96,000 or above", "yes_bid": 20, "yes_ask": 22, "no_bid": 77, "no_ask": 79},
        ], None)

        data, err = fetch_kalshi_data_struct()
        assert err is None
        assert data["event_ticker"] == "KXBTCD-25DEC0114"
        assert data["current_price"] == 95500.0
        assert len(data["markets"]) == 2
        # Sorted by strike
        assert data["markets"][0]["strike"] == 94000.0
        assert data["markets"][1]["strike"] == 96000.0

    @patch('fetch_current_kalshi.get_kalshi_markets')
    @patch('fetch_current_kalshi.get_binance_current_price')
    @patch('fetch_current_kalshi.get_current_market_urls')
    def test_invalid_subtitle_filtered(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([
            {"subtitle": "$94,000 or above", "yes_bid": 85, "yes_ask": 87, "no_bid": 12, "no_ask": 14},
            {"subtitle": "invalid subtitle", "yes_bid": 50, "yes_ask": 52, "no_bid": 47, "no_ask": 49},
        ], None)

        data, err = fetch_kalshi_data_struct()
        assert err is None
        assert len(data["markets"]) == 1  # Invalid subtitle filtered out

    @patch('fetch_current_kalshi.get_kalshi_markets')
    @patch('fetch_current_kalshi.get_binance_current_price')
    @patch('fetch_current_kalshi.get_current_market_urls')
    def test_empty_markets(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([], None)

        data, err = fetch_kalshi_data_struct()
        assert err is None
        assert data["markets"] == []
        assert data["event_ticker"] == "KXBTCD-25DEC0114"

    @patch('fetch_current_kalshi.get_kalshi_markets')
    @patch('fetch_current_kalshi.get_binance_current_price')
    @patch('fetch_current_kalshi.get_current_market_urls')
    def test_kalshi_api_error(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = (None, "API Error")

        data, err = fetch_kalshi_data_struct()
        assert data is None
        assert "Kalshi Error" in err

    @patch('fetch_current_kalshi.get_kalshi_markets')
    @patch('fetch_current_kalshi.get_binance_current_price')
    @patch('fetch_current_kalshi.get_current_market_urls')
    def test_binance_error_still_returns_data(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (None, "Binance Error")
        mock_kalshi.return_value = ([
            {"subtitle": "$94,000 or above", "yes_bid": 85, "yes_ask": 87, "no_bid": 12, "no_ask": 14},
        ], None)

        data, err = fetch_kalshi_data_struct()
        assert err is None
        assert data["current_price"] is None
        assert len(data["markets"]) == 1

    @patch('fetch_current_kalshi.get_kalshi_markets')
    @patch('fetch_current_kalshi.get_binance_current_price')
    @patch('fetch_current_kalshi.get_current_market_urls')
    def test_markets_sorted_by_strike(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        # Return unsorted
        mock_kalshi.return_value = ([
            {"subtitle": "$96,000 or above", "yes_bid": 20, "yes_ask": 22, "no_bid": 77, "no_ask": 79},
            {"subtitle": "$94,000 or above", "yes_bid": 85, "yes_ask": 87, "no_bid": 12, "no_ask": 14},
        ], None)

        data, err = fetch_kalshi_data_struct()
        assert data["markets"][0]["strike"] < data["markets"][1]["strike"]
