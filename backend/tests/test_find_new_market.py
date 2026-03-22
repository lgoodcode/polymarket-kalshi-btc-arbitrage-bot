import datetime
import pytz
import pytest

from find_new_market import generate_slug, generate_market_url

ET = pytz.timezone('US/Eastern')
UTC = pytz.utc


class TestGenerateSlug:
    def test_known_time_1pm(self):
        t = ET.localize(datetime.datetime(2025, 11, 26, 13, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-november-26-1pm-et"

    def test_known_time_2pm(self):
        t = ET.localize(datetime.datetime(2026, 3, 22, 14, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-march-22-2pm-et"

    def test_midnight(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 0, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-12am-et"

    def test_noon(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 12, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-12pm-et"

    def test_single_digit_morning(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 9, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-9am-et"

    def test_single_digit_afternoon(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 15, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-3pm-et"

    def test_11pm(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 23, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-11pm-et"

    def test_1am(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 1, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-1am-et"

    def test_utc_input_converts_to_et(self):
        # 7PM UTC = 2PM ET (EST, UTC-5)
        t = UTC.localize(datetime.datetime(2025, 12, 1, 19, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-2pm-et"

    def test_naive_datetime_assumed_utc(self):
        # Naive datetime should be treated as UTC
        t = datetime.datetime(2025, 12, 1, 19, 0, 0)
        assert generate_slug(t) == "bitcoin-up-or-down-december-1-2pm-et"

    def test_dst_spring_forward(self):
        # March 9, 2025: clocks spring forward EDT (UTC-4)
        # 18:00 UTC = 2PM EDT
        t = UTC.localize(datetime.datetime(2025, 3, 10, 18, 0, 0))
        assert generate_slug(t) == "bitcoin-up-or-down-march-10-2pm-et"

    def test_day_no_leading_zero(self):
        t = ET.localize(datetime.datetime(2025, 1, 5, 10, 0, 0))
        slug = generate_slug(t)
        assert "-5-" in slug  # day=5, not 05


class TestGenerateMarketUrl:
    def test_url_format(self):
        t = ET.localize(datetime.datetime(2025, 11, 26, 13, 0, 0))
        url = generate_market_url(t)
        assert url == "https://polymarket.com/event/bitcoin-up-or-down-november-26-1pm-et"

    def test_url_starts_with_base(self):
        t = ET.localize(datetime.datetime(2025, 12, 1, 12, 0, 0))
        url = generate_market_url(t)
        assert url.startswith("https://polymarket.com/event/")
