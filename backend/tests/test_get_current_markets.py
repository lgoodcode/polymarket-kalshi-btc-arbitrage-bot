import datetime
import pytz
import pytest
from unittest.mock import patch

from get_current_markets import get_current_market_urls

ET = pytz.timezone('US/Eastern')
UTC = pytz.utc


class TestGetCurrentMarketUrls:
    @patch('get_current_markets.datetime')
    def test_target_time_is_current_hour_floor(self, mock_dt):
        mock_dt.datetime.now.return_value = datetime.datetime(2025, 12, 1, 14, 35, 22, tzinfo=UTC)
        mock_dt.timedelta = datetime.timedelta

        result = get_current_market_urls()
        # target_time should be 14:00 UTC (floor of 14:35)
        assert result["target_time_utc"] == datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)

    @patch('get_current_markets.datetime')
    def test_polymarket_url_uses_target_time(self, mock_dt):
        mock_dt.datetime.now.return_value = datetime.datetime(2025, 12, 1, 14, 30, 0, tzinfo=UTC)
        mock_dt.timedelta = datetime.timedelta

        result = get_current_market_urls()
        # 14:00 UTC = 9:00 AM ET (EST)
        assert "9am-et" in result["polymarket"]

    @patch('get_current_markets.datetime')
    def test_kalshi_url_uses_target_time_plus_1hr(self, mock_dt):
        mock_dt.datetime.now.return_value = datetime.datetime(2025, 12, 1, 14, 30, 0, tzinfo=UTC)
        mock_dt.timedelta = datetime.timedelta

        result = get_current_market_urls()
        # Kalshi = target_time + 1hr = 15:00 UTC = 10:00 ET
        # Kalshi slug: kxbtcd-25dec0110 (10:00 ET in 24hr)
        assert "0110" in result["kalshi"]

    @patch('get_current_markets.datetime')
    def test_et_conversion_in_result(self, mock_dt):
        mock_dt.datetime.now.return_value = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        mock_dt.timedelta = datetime.timedelta

        result = get_current_market_urls()
        et_time = result["target_time_et"]
        assert et_time.tzinfo is not None
        assert et_time.hour == 9  # 14:00 UTC = 9:00 AM EST

    @patch('get_current_markets.datetime')
    def test_at_exact_hour(self, mock_dt):
        mock_dt.datetime.now.return_value = datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)
        mock_dt.timedelta = datetime.timedelta

        result = get_current_market_urls()
        assert result["target_time_utc"] == datetime.datetime(2025, 12, 1, 14, 0, 0, tzinfo=UTC)

    @patch('get_current_markets.datetime')
    def test_just_before_next_hour(self, mock_dt):
        mock_dt.datetime.now.return_value = datetime.datetime(2025, 12, 1, 14, 59, 59, tzinfo=UTC)
        mock_dt.timedelta = datetime.timedelta

        result = get_current_market_urls()
        # Still floors to 14:00
        assert result["target_time_utc"].hour == 14
        assert result["target_time_utc"].minute == 0
