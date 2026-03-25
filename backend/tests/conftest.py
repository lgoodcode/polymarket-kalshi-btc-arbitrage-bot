import sys
import os
import pytest
import datetime
import pytz
from decimal import Decimal

# Add backend to path so tests can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ET = pytz.timezone('US/Eastern')
UTC = pytz.utc


# --- Polymarket fixtures ---

@pytest.fixture
def sample_clob_response():
    return {
        "bids": [{"price": "0.45", "size": "100"}, {"price": "0.44", "size": "200"}],
        "asks": [{"price": "0.47", "size": "150"}, {"price": "0.48", "size": "300"}]
    }


@pytest.fixture
def sample_clob_response_empty_asks():
    return {
        "bids": [{"price": "0.45", "size": "100"}],
        "asks": []
    }


@pytest.fixture
def sample_clob_response_empty_both():
    return {"bids": [], "asks": []}


@pytest.fixture
def sample_poly_event_response():
    return [{
        "markets": [{
            "clobTokenIds": '["token_up_123", "token_down_456"]',
            "outcomes": '["Up", "Down"]'
        }]
    }]


@pytest.fixture
def sample_poly_event_response_reversed_outcomes():
    return [{
        "markets": [{
            "clobTokenIds": '["token_down_456", "token_up_123"]',
            "outcomes": '["Down", "Up"]'
        }]
    }]


# --- Kalshi fixtures ---

@pytest.fixture
def sample_kalshi_api_response():
    return {
        "markets": [
            {"subtitle": "$94,000 or above", "yes_bid_dollars": "0.8500", "yes_ask_dollars": "0.8700", "no_bid_dollars": "0.1200", "no_ask_dollars": "0.1400"},
            {"subtitle": "$95,000 or above", "yes_bid_dollars": "0.5000", "yes_ask_dollars": "0.5200", "no_bid_dollars": "0.4700", "no_ask_dollars": "0.4900"},
            {"subtitle": "$96,000 or above", "yes_bid_dollars": "0.2000", "yes_ask_dollars": "0.2200", "no_bid_dollars": "0.7700", "no_ask_dollars": "0.7900"},
        ]
    }


# --- Binance fixtures ---

@pytest.fixture
def sample_binance_price_response():
    return {"symbol": "BTCUSDT", "price": "95500.00"}


@pytest.fixture
def sample_binance_kline_response():
    return [[1700000000000, "95000.00", "96000.00", "94500.00", "95800.00", "1000"]]


# --- Structured data fixtures (for api.py / arbitrage_bot.py tests) ---

@pytest.fixture
def sample_poly_data():
    return {
        "price_to_beat": Decimal("95000"),
        "current_price": Decimal("95500"),
        "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.47")},
        "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        "slug": "bitcoin-up-or-down-march-22-2pm-et",
        "target_time_utc": datetime.datetime(2026, 3, 22, 19, 0, 0, tzinfo=UTC)
    }


@pytest.fixture
def sample_kalshi_data():
    return {
        "event_ticker": "KXBTCD-26MAR2215",
        "current_price": Decimal("95500"),
        "markets": [
            {"strike": Decimal("94000"), "yes_bid": Decimal("0.85"), "yes_ask": Decimal("0.87"), "no_bid": Decimal("0.12"), "no_ask": Decimal("0.14"), "subtitle": "$94,000 or above"},
            {"strike": Decimal("95000"), "yes_bid": Decimal("0.50"), "yes_ask": Decimal("0.52"), "no_bid": Decimal("0.47"), "no_ask": Decimal("0.49"), "subtitle": "$95,000 or above"},
            {"strike": Decimal("96000"), "yes_bid": Decimal("0.20"), "yes_ask": Decimal("0.22"), "no_bid": Decimal("0.77"), "no_ask": Decimal("0.79"), "subtitle": "$96,000 or above"},
        ]
    }


@pytest.fixture
def sample_kalshi_data_with_unpriced():
    """Kalshi data where some markets have 0 ask prices."""
    return {
        "event_ticker": "KXBTCD-26MAR2215",
        "current_price": Decimal("95500"),
        "markets": [
            {"strike": Decimal("94000"), "yes_bid": Decimal("0.85"), "yes_ask": Decimal("0.87"), "no_bid": Decimal("0.12"), "no_ask": Decimal("0.14"), "subtitle": "$94,000 or above"},
            {"strike": Decimal("95000"), "yes_bid": Decimal("0"), "yes_ask": Decimal("0"), "no_bid": Decimal("0"), "no_ask": Decimal("0"), "subtitle": "$95,000 or above"},
            {"strike": Decimal("96000"), "yes_bid": Decimal("0.20"), "yes_ask": Decimal("0.22"), "no_bid": Decimal("0.77"), "no_ask": Decimal("0.79"), "subtitle": "$96,000 or above"},
        ]
    }


@pytest.fixture
def arb_poly_data():
    """Polymarket data designed to produce an arbitrage opportunity."""
    return {
        "price_to_beat": Decimal("95000"),
        "current_price": Decimal("95500"),
        "prices": {"Up": Decimal("0.40"), "Down": Decimal("0.35")},
        "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        "slug": "bitcoin-up-or-down-march-22-2pm-et",
        "target_time_utc": datetime.datetime(2026, 3, 22, 19, 0, 0, tzinfo=UTC)
    }


@pytest.fixture
def arb_kalshi_data():
    """Kalshi data designed to produce an arbitrage with arb_poly_data."""
    return {
        "event_ticker": "KXBTCD-26MAR2215",
        "current_price": Decimal("95500"),
        "markets": [
            {"strike": Decimal("94000"), "yes_bid": Decimal("0.40"), "yes_ask": Decimal("0.42"), "no_bid": Decimal("0.55"), "no_ask": Decimal("0.58"), "subtitle": "$94,000 or above"},
        ]
    }
