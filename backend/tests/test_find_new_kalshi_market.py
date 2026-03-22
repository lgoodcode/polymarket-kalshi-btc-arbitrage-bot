import datetime
import pytz
import pytest

from find_new_kalshi_market import generate_kalshi_slug, generate_kalshi_url

ET = pytz.timezone('US/Eastern')
UTC = pytz.utc


class TestGenerateKalshiSlug:
    def test_known_time(self):
        t = ET.localize(datetime.datetime(2025, 11, 26, 14, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-25nov2614"

    def test_midnight(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 0, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-25dec0100"

    def test_single_digit_day_padded(self):
        t = ET.localize(datetime.datetime(2025, 1, 5, 10, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-25jan0510"

    def test_24hr_format(self):
        t = ET.localize(datetime.datetime(2025, 6, 15, 23, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-25jun1523"

    def test_year_2026(self):
        t = ET.localize(datetime.datetime(2026, 3, 22, 14, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-26mar2214"

    def test_utc_input_converts_to_et(self):
        # 19:00 UTC = 14:00 ET (EST, UTC-5)
        t = UTC.localize(datetime.datetime(2025, 12, 1, 19, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-25dec0114"

    def test_naive_datetime_assumed_utc(self):
        t = datetime.datetime(2025, 12, 1, 19, 0, 0)
        assert generate_kalshi_slug(t) == "kxbtcd-25dec0114"

    def test_month_lowercase(self):
        t = ET.localize(datetime.datetime(2025, 8, 15, 12, 0, 0))
        slug = generate_kalshi_slug(t)
        assert "aug" in slug

    def test_dst_edt_period(self):
        # During EDT (UTC-4): 18:00 UTC = 14:00 EDT
        t = UTC.localize(datetime.datetime(2025, 7, 1, 18, 0, 0))
        assert generate_kalshi_slug(t) == "kxbtcd-25jul0114"


class TestGenerateKalshiUrl:
    def test_url_format(self):
        t = ET.localize(datetime.datetime(2025, 11, 26, 14, 0, 0))
        url = generate_kalshi_url(t)
        assert url == "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-25nov2614"

    def test_url_starts_with_base(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 12, 0, 0))
        url = generate_kalshi_url(t)
        assert url.startswith("https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/")
