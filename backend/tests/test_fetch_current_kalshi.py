import datetime
import pytz
import pytest
from unittest.mock import patch, AsyncMock

from fetch_current_kalshi import (
    parse_strike,
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
        assert parse_strike("$0 or above") == 0.0

    def test_multiple_dollar_signs(self):
        result = parse_strike("$94,000 to $95,000")
        assert result == 94000.0

    def test_decimal_strike(self):
        """SEC-013: edge case with decimals in subtitle."""
        result = parse_strike("$96,250.00 or above")
        assert result == 96250.0


# --- get_kalshi_markets tests ---

class TestGetKalshiMarkets:
    @patch('fetch_current_kalshi.fetch_json', new_callable=AsyncMock)
    async def test_success(self, mock_fetch, sample_kalshi_api_response):
        mock_fetch.return_value = sample_kalshi_api_response
        markets, err = await get_kalshi_markets(AsyncMock(), "KXBTCD-25NOV2614")
        assert err is None
        assert len(markets) == 3

    @patch('fetch_current_kalshi.fetch_json', new_callable=AsyncMock)
    async def test_empty_markets(self, mock_fetch):
        mock_fetch.return_value = {"markets": []}
        markets, err = await get_kalshi_markets(AsyncMock(), "KXBTCD-UNKNOWN")
        assert err is None
        assert markets == []

    @patch('fetch_current_kalshi.fetch_json', new_callable=AsyncMock)
    async def test_http_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("500 Server Error")
        markets, err = await get_kalshi_markets(AsyncMock(), "KXBTCD-25NOV2614")
        assert markets is None
        assert "500 Server Error" in err


# --- fetch_kalshi_data_struct tests ---

class TestFetchKalshiDataStruct:
    @patch('fetch_current_kalshi.get_kalshi_markets', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_current_market_urls')
    async def test_normal_flow_dollars_format(self, mock_urls, mock_binance, mock_kalshi):
        """Test parsing with _dollars string fields (post-March 2026)."""
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([
            {
                "subtitle": "$94,000 or above",
                "yes_bid_dollars": "0.8500", "yes_ask_dollars": "0.8700",
                "no_bid_dollars": "0.1200", "no_ask_dollars": "0.1400",
            },
            {
                "subtitle": "$96,000 or above",
                "yes_bid_dollars": "0.2000", "yes_ask_dollars": "0.2200",
                "no_bid_dollars": "0.7700", "no_ask_dollars": "0.7900",
            },
        ], None)

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_kalshi_data_struct(session)
        assert err is None
        assert len(data["markets"]) == 2
        assert data["markets"][0]["yes_ask"] == 0.87
        assert data["markets"][0]["no_ask"] == 0.14
        assert data["markets"][1]["yes_ask"] == 0.22
        assert data["markets"][1]["no_ask"] == 0.79

    @patch('fetch_current_kalshi.get_kalshi_markets', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_current_market_urls')
    async def test_invalid_subtitle_filtered(self, mock_urls, mock_binance, mock_kalshi, caplog):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([
            {"subtitle": "$94,000 or above", "yes_bid_dollars": "0.8500", "yes_ask_dollars": "0.8700", "no_bid_dollars": "0.1200", "no_ask_dollars": "0.1400"},
            {"subtitle": "invalid subtitle", "yes_bid_dollars": "0.5000", "yes_ask_dollars": "0.5200", "no_bid_dollars": "0.4700", "no_ask_dollars": "0.4900"},
        ], None)

        session = AsyncMock()
        session.close = AsyncMock()
        import logging
        with caplog.at_level(logging.WARNING, logger="fetch_current_kalshi"):
            data, err = await fetch_kalshi_data_struct(session)
        assert err is None
        assert len(data["markets"]) == 1
        assert any("invalid subtitle" in rec.message for rec in caplog.records)

    @patch('fetch_current_kalshi.get_kalshi_markets', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_current_market_urls')
    async def test_empty_markets(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([], None)

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_kalshi_data_struct(session)
        assert err is None
        assert data["markets"] == []
        assert data["event_ticker"] == "KXBTCD-25DEC0114"

    @patch('fetch_current_kalshi.get_kalshi_markets', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_current_market_urls')
    async def test_kalshi_api_error(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = (None, "API Error")

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_kalshi_data_struct(session)
        assert data is None
        assert "Kalshi Error" in err

    @patch('fetch_current_kalshi.get_kalshi_markets', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_current_market_urls')
    async def test_binance_error_still_returns_data(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (None, "Binance Error")
        mock_kalshi.return_value = ([
            {"subtitle": "$94,000 or above", "yes_bid_dollars": "0.8500", "yes_ask_dollars": "0.8700", "no_bid_dollars": "0.1200", "no_ask_dollars": "0.1400"},
        ], None)

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_kalshi_data_struct(session)
        assert err is None
        assert data["current_price"] is None
        assert len(data["markets"]) == 1

    @patch('fetch_current_kalshi.get_kalshi_markets', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_binance_current_price', new_callable=AsyncMock)
    @patch('fetch_current_kalshi.get_current_market_urls')
    async def test_markets_sorted_by_strike(self, mock_urls, mock_binance, mock_kalshi):
        mock_urls.return_value = {
            "kalshi": "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25dec0114",
            "polymarket": "...",
            "target_time_utc": datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC),
            "target_time_et": datetime.datetime(2025, 12, 1, 9, 0, 0),
        }
        mock_binance.return_value = (95500.0, None)
        mock_kalshi.return_value = ([
            {"subtitle": "$96,000 or above", "yes_bid_dollars": "0.2000", "yes_ask_dollars": "0.2200", "no_bid_dollars": "0.7700", "no_ask_dollars": "0.7900"},
            {"subtitle": "$94,000 or above", "yes_bid_dollars": "0.8500", "yes_ask_dollars": "0.8700", "no_bid_dollars": "0.1200", "no_ask_dollars": "0.1400"},
        ], None)

        session = AsyncMock()
        session.close = AsyncMock()
        data, err = await fetch_kalshi_data_struct(session)
        assert data["markets"][0]["strike"] < data["markets"][1]["strike"]
