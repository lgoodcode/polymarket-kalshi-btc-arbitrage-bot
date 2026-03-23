"""
Tier 1: Mock-based integration tests.

These tests mock ONLY at the HTTP boundary (requests.get) and let all internal
logic run naturally: slug generation, API response parsing, arbitrage detection,
fee estimation, and response formatting.

Unlike unit tests which mock individual functions, these verify the full pipeline.
"""
import json
import os
import datetime
import pytest
import pytz
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import requests as requests_lib

from api import app

UTC = pytz.utc
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

client = TestClient(app)


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


# Frozen time: 2026-03-23 14:30:00 UTC = 10:30 AM ET (EDT)
# Polymarket target = 14:00 UTC = 10:00 AM ET → slug: bitcoin-up-or-down-march-23-10am-et
# Kalshi target = 15:00 UTC = 11:00 AM ET → ticker: KXBTCD-26MAR2311
FROZEN_TIME = datetime.datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)


def make_mock_response(json_data, status_code=200):
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data
    mock_resp.status_code = status_code
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def make_error_response(status_code=500):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status.side_effect = requests_lib.exceptions.HTTPError(
        f"{status_code} Server Error"
    )
    return mock_resp


def build_router(poly_gamma, poly_clob_up, poly_clob_down, kalshi_markets,
                 binance_price, binance_kline, overrides=None):
    """
    Build a side_effect function that routes requests.get calls
    to different mock responses based on the URL.
    overrides: dict mapping URL substring → response override (or 'error')
    """
    overrides = overrides or {}

    def router(url, **kwargs):
        # Check overrides first
        for pattern, override in overrides.items():
            if pattern in url:
                if override == "error":
                    return make_error_response(500)
                elif override == "timeout":
                    raise requests_lib.exceptions.Timeout("Connection timed out")
                return make_mock_response(override)

        params = kwargs.get("params", {})

        if "gamma-api.polymarket.com" in url:
            return make_mock_response(poly_gamma)
        elif "clob.polymarket.com" in url:
            token_id = params.get("token_id", "")
            if "up" in token_id.lower():
                return make_mock_response(poly_clob_up)
            else:
                return make_mock_response(poly_clob_down)
        elif "elections.kalshi.com" in url:
            return make_mock_response(kalshi_markets)
        elif "binance.com" in url:
            if "klines" in url:
                return make_mock_response(binance_kline)
            else:
                return make_mock_response(binance_price)
        return make_mock_response({})

    return router


@pytest.fixture
def arb_fixtures():
    """Fixture set that produces arbitrage. Up=0.48, Down=0.47 (sum=0.95)."""
    return {
        "poly_gamma": load_fixture("arb_poly_gamma.json"),
        "poly_clob_up": load_fixture("arb_poly_clob_up.json"),
        "poly_clob_down": load_fixture("arb_poly_clob_down.json"),
        "kalshi_markets": load_fixture("arb_kalshi_markets.json"),
        "binance_price": load_fixture("binance_price.json"),
        "binance_kline": load_fixture("binance_kline.json"),
    }


@pytest.fixture
def noarb_fixtures():
    """Fixture set that produces NO arbitrage. Up=0.55, Down=0.47 (sum=1.02)."""
    return {
        "poly_gamma": load_fixture("noarb_poly_gamma.json"),
        "poly_clob_up": load_fixture("noarb_poly_clob_up.json"),
        "poly_clob_down": load_fixture("noarb_poly_clob_down.json"),
        "kalshi_markets": load_fixture("noarb_kalshi_markets.json"),
        "binance_price": load_fixture("binance_price.json"),
        "binance_kline": load_fixture("binance_kline.json"),
    }


def _freeze_time_and_mock(mock_requests_get, mock_gcm_dt, fixtures, overrides=None):
    """Common setup: freeze time and configure request routing."""
    mock_gcm_dt.datetime.now.return_value = FROZEN_TIME
    mock_gcm_dt.timedelta = datetime.timedelta
    router = build_router(**fixtures, overrides=overrides or {})
    mock_requests_get.side_effect = router


# =====================================================================
# Tier 1 Integration Tests
# =====================================================================

@pytest.mark.integration
class TestFullPipelineArbitrageFound:
    """Happy path: realistic data produces arbitrage opportunities."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_arbitrage_found(self, mock_get, mock_dt, arb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, arb_fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert data["errors"] == []
        assert data["polymarket"] is not None
        assert data["kalshi"] is not None
        assert len(data["checks"]) > 0
        assert len(data["opportunities"]) > 0

        opp = data["opportunities"][0]
        assert opp["is_arbitrage"] is True
        assert opp["total_cost"] < 1.00
        assert opp["margin"] > 0
        assert "estimated_fees" in opp
        assert "margin_after_fees" in opp
        assert "profitable_after_fees" in opp


@pytest.mark.integration
class TestFullPipelineNoArbitrage:
    """Full pipeline with prices where all combos have total_cost >= $1.00."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_no_arbitrage(self, mock_get, mock_dt, noarb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, noarb_fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert data["errors"] == []
        assert len(data["checks"]) > 0
        assert len(data["opportunities"]) == 0
        for check in data["checks"]:
            assert check["is_arbitrage"] is False


@pytest.mark.integration
class TestFullPipelineResponseStructure:
    """Validate response JSON has all expected keys for frontend."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_api_response_structure(self, mock_get, mock_dt, noarb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, noarb_fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        # Top-level keys
        for key in ["timestamp", "polymarket", "kalshi", "checks", "opportunities", "errors"]:
            assert key in data

        # Polymarket structure
        poly = data["polymarket"]
        for key in ["price_to_beat", "current_price", "prices", "slug"]:
            assert key in poly
        assert "Up" in poly["prices"]
        assert "Down" in poly["prices"]

        # Kalshi structure
        kalshi = data["kalshi"]
        for key in ["event_ticker", "current_price", "markets"]:
            assert key in kalshi

        # Check structure
        if data["checks"]:
            check = data["checks"][0]
            for key in ["kalshi_strike", "kalshi_yes", "kalshi_no", "type",
                        "poly_leg", "kalshi_leg", "poly_cost", "kalshi_cost",
                        "total_cost", "is_arbitrage", "margin"]:
                assert key in check


@pytest.mark.integration
class TestFullPipelinePolymarketDown:
    """Polymarket Gamma API returns 500 → graceful error."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_polymarket_api_down(self, mock_get, mock_dt, noarb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, noarb_fixtures,
                              overrides={"gamma-api.polymarket.com": "error"})

        resp = client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert len(data["errors"]) > 0
        assert data["checks"] == []
        assert data["opportunities"] == []


@pytest.mark.integration
class TestFullPipelineKalshiDown:
    """Kalshi API returns 500 → graceful error."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_kalshi_api_down(self, mock_get, mock_dt, noarb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, noarb_fixtures,
                              overrides={"elections.kalshi.com": "error"})

        resp = client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert len(data["errors"]) > 0
        assert data["checks"] == []


@pytest.mark.integration
class TestFullPipelineBinanceDown:
    """Binance API errors → pipeline degrades gracefully."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_binance_api_down(self, mock_get, mock_dt, noarb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, noarb_fixtures,
                              overrides={"binance.com": "error"})

        resp = client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        # Binance errors don't prevent poly/kalshi data from being fetched,
        # but price_to_beat and current_price may be None


@pytest.mark.integration
class TestFullPipelineStalePrices:
    """Up+Down > 1.15 → sanity check triggers."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_stale_polymarket_prices(self, mock_get, mock_dt, noarb_fixtures):
        stale_clob_up = {"bids": [{"price": "0.73", "size": "100"}],
                         "asks": [{"price": "0.75", "size": "100"}]}
        stale_clob_down = {"bids": [{"price": "0.73", "size": "100"}],
                           "asks": [{"price": "0.75", "size": "100"}]}
        fixtures = dict(noarb_fixtures)
        fixtures["poly_clob_up"] = stale_clob_up
        fixtures["poly_clob_down"] = stale_clob_down

        _freeze_time_and_mock(mock_get, mock_dt, fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        assert any("sanity check" in e for e in data["errors"])
        assert data["checks"] == []


@pytest.mark.integration
class TestFullPipelineUnpricedMarkets:
    """Markets with 0 asks are skipped."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_unpriced_kalshi_markets(self, mock_get, mock_dt, noarb_fixtures):
        kalshi_with_unpriced = {
            "markets": [
                {"subtitle": "$94,000 or above",
                 "yes_bid_dollars": "0.8700", "yes_ask_dollars": "0.8800",
                 "no_bid_dollars": "0.1100", "no_ask_dollars": "0.1300"},
                {"subtitle": "$95,000 or above",
                 "yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.0000",
                 "no_bid_dollars": "0.0000", "no_ask_dollars": "0.0000"},
                {"subtitle": "$96,000 or above",
                 "yes_bid_dollars": "0.2000", "yes_ask_dollars": "0.2200",
                 "no_bid_dollars": "0.7700", "no_ask_dollars": "0.7900"},
            ]
        }
        fixtures = dict(noarb_fixtures)
        fixtures["kalshi_markets"] = kalshi_with_unpriced

        _freeze_time_and_mock(mock_get, mock_dt, fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        strikes_checked = [c["kalshi_strike"] for c in data["checks"]]
        assert 95000.0 not in strikes_checked


@pytest.mark.integration
class TestFullPipelineEqualStrikes:
    """Poly strike == Kalshi strike → both combos checked."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_equal_strikes(self, mock_get, mock_dt, arb_fixtures):
        kalshi_equal = {
            "markets": [
                {"subtitle": "$95,000 or above",
                 "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3500",
                 "no_bid_dollars": "0.3000", "no_ask_dollars": "0.3500"},
            ]
        }
        fixtures = dict(arb_fixtures)
        fixtures["kalshi_markets"] = kalshi_equal

        _freeze_time_and_mock(mock_get, mock_dt, fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        equal_checks = [c for c in data["checks"] if c["type"] == "Equal"]
        assert len(equal_checks) == 2
        legs = {(c["poly_leg"], c["kalshi_leg"]) for c in equal_checks}
        assert ("Down", "Yes") in legs
        assert ("Up", "No") in legs


@pytest.mark.integration
class TestFullPipelineFeeErosion:
    """Margin exists pre-fees but not post-fees."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_fee_erosion(self, mock_get, mock_dt):
        # Poly Up=0.50, Down=0.48 (sum=0.98, passes sanity)
        poly_gamma = load_fixture("noarb_poly_gamma.json")
        tight_clob_up = {"bids": [{"price": "0.48", "size": "100"}],
                         "asks": [{"price": "0.50", "size": "100"}]}
        tight_clob_down = {"bids": [{"price": "0.46", "size": "100"}],
                           "asks": [{"price": "0.48", "size": "100"}]}
        # Kalshi market at $96K: poly_strike(95K) < kalshi(96K)
        # Strategy = Poly Up(0.50) + Kalshi No(0.48) = 0.98 → margin=0.02
        # Fees: 0.50*0.02 + 0.52*0.07 = 0.01+0.0364 = 0.0464 > 0.02 → NOT profitable
        kalshi_tight = {
            "markets": [
                {"subtitle": "$96,000 or above",
                 "yes_bid_dollars": "0.5100", "yes_ask_dollars": "0.5200",
                 "no_bid_dollars": "0.4600", "no_ask_dollars": "0.4800"},
            ]
        }

        fixtures = {
            "poly_gamma": poly_gamma,
            "poly_clob_up": tight_clob_up,
            "poly_clob_down": tight_clob_down,
            "kalshi_markets": kalshi_tight,
            "binance_price": load_fixture("binance_price.json"),
            "binance_kline": load_fixture("binance_kline.json"),
        }
        _freeze_time_and_mock(mock_get, mock_dt, fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        for opp in data["opportunities"]:
            assert opp["is_arbitrage"] is True
            assert opp["margin"] > 0
            assert opp["profitable_after_fees"] is False
            assert opp["margin_after_fees"] < 0


@pytest.mark.integration
class TestFullPipelineMultipleOpportunities:
    """Multiple Kalshi strikes produce arb → all returned."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_multiple_opportunities(self, mock_get, mock_dt, arb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, arb_fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        # With poly Up=0.48, Down=0.47 and cheap Kalshi markets,
        # multiple strikes should produce opportunities
        assert len(data["opportunities"]) >= 2


@pytest.mark.integration
class TestFullPipelineMarketWindow:
    """Only ±4 markets around closest strike are checked."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_market_selection_window(self, mock_get, mock_dt, noarb_fixtures):
        _freeze_time_and_mock(mock_get, mock_dt, noarb_fixtures)

        resp = client.get("/arbitrage")
        data = resp.json()

        # 9 Kalshi markets in fixture, ±4 window → max ~9 checks (or 10 with equal strike)
        assert len(data["checks"]) <= 11


@pytest.mark.integration
class TestCliBotFullPipeline:
    """check_arbitrage() runs with mocked HTTP, verify stdout."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_cli_bot_full_pipeline(self, mock_get, mock_dt, arb_fixtures, capsys):
        _freeze_time_and_mock(mock_get, mock_dt, arb_fixtures)

        from arbitrage_bot import check_arbitrage
        check_arbitrage()

        captured = capsys.readouterr()
        assert "Scanning for arbitrage" in captured.out
        assert "POLYMARKET" in captured.out
        assert "ARBITRAGE FOUND" in captured.out
        assert "Est. Fees" in captured.out


@pytest.mark.integration
class TestFullPipelineTimeout:
    """requests.get raises Timeout → error propagated cleanly."""

    @patch("get_current_markets.datetime")
    @patch("requests.get")
    def test_full_pipeline_timeout_handling(self, mock_get, mock_dt):
        mock_dt.datetime.now.return_value = FROZEN_TIME
        mock_dt.timedelta = datetime.timedelta
        mock_get.side_effect = requests_lib.exceptions.Timeout("Connection timed out")

        resp = client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert len(data["errors"]) > 0
        assert data["checks"] == []
