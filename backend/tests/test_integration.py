"""
Tier 1: Mock-based integration tests.

These tests mock at the fetch_*_data_struct level and let the arbitrage
logic run naturally. They verify the full pipeline from API endpoint
through to response formatting.
"""
import json
import os
import datetime
import pytest
import pytz
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from api import app, clear_cache

UTC = pytz.utc
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the server-side cache before each test."""
    clear_cache()


def _make_poly_data(up, down, strike=95000.0, current=95500.0):
    return {
        "price_to_beat": strike,
        "current_price": current,
        "prices": {"Up": up, "Down": down},
        "slug": "bitcoin-up-or-down-march-23-10am-et",
        "target_time_utc": datetime.datetime(2026, 3, 23, 14, 0, 0, tzinfo=UTC),
    }


def _make_kalshi_data(markets, ticker="KXBTCD-26MAR2311", current=95500.0):
    return {
        "event_ticker": ticker,
        "current_price": current,
        "markets": markets,
    }


def _make_kalshi_market(strike, yes_ask, no_ask, yes_bid=None, no_bid=None):
    return {
        "strike": strike,
        "yes_bid": yes_bid or (1.0 - no_ask),
        "yes_ask": yes_ask,
        "no_bid": no_bid or (1.0 - yes_ask),
        "no_ask": no_ask,
        "subtitle": f"${int(strike):,} or above",
    }


# =====================================================================
# Tier 1 Integration Tests
# =====================================================================

@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineArbitrageFound:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_arbitrage_found(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.48, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(94000, 0.42, 0.58),
            _make_kalshi_market(94500, 0.38, 0.62),
            _make_kalshi_market(95000, 0.35, 0.35),
        ]), None)

        resp = await client.get("/arbitrage")
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
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineNoArbitrage:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_no_arbitrage(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.55, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(94000, 0.87, 0.14),
            _make_kalshi_market(95000, 0.55, 0.49),
            _make_kalshi_market(96000, 0.22, 0.79),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert data["errors"] == []
        assert len(data["checks"]) > 0
        assert len(data["opportunities"]) == 0
        for check in data["checks"]:
            assert check["is_arbitrage"] is False


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineResponseStructure:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_api_response_structure(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.55, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(95000, 0.52, 0.49),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        for key in ["timestamp", "polymarket", "kalshi", "checks", "opportunities", "errors", "scan_id", "fee_disclaimer"]:
            assert key in data

        poly = data["polymarket"]
        for key in ["price_to_beat", "current_price", "prices", "slug"]:
            assert key in poly
        assert "Up" in poly["prices"]
        assert "Down" in poly["prices"]

        kalshi = data["kalshi"]
        for key in ["event_ticker", "current_price", "markets"]:
            assert key in kalshi

        if data["checks"]:
            check = data["checks"][0]
            for key in ["kalshi_strike", "kalshi_yes", "kalshi_no", "type",
                        "poly_leg", "kalshi_leg", "poly_cost", "kalshi_cost",
                        "total_cost", "is_arbitrage", "margin"]:
                assert key in check


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelinePolymarketDown:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_polymarket_api_down(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (None, "Polymarket Error: 500 Server Error")
        mock_kalshi.return_value = (_make_kalshi_data([]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert len(data["errors"]) > 0
        assert data["checks"] == []
        assert data["opportunities"] == []


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineKalshiDown:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_kalshi_api_down(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.55, 0.47), None)
        mock_kalshi.return_value = (None, "Kalshi Error: API down")

        resp = await client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert len(data["errors"]) > 0
        assert data["checks"] == []


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(None, "Binance down"))
class TestFullPipelineBinanceDown:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_binance_api_down(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        # Binance errors result in None prices but data still returned
        mock_poly.return_value = ({
            "price_to_beat": None,
            "current_price": None,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(95000, 0.52, 0.49),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert resp.status_code == 200


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineStalePrices:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_stale_polymarket_prices(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.75, 0.75), None)  # Sum = 1.50 > 1.15
        mock_kalshi.return_value = (_make_kalshi_data([]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        assert any("sanity check" in e for e in data["errors"])
        assert data["checks"] == []


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineUnpricedMarkets:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_unpriced_kalshi_markets(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.55, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(94000, 0.88, 0.13),
            _make_kalshi_market(95000, 0, 0),  # Unpriced
            _make_kalshi_market(96000, 0.22, 0.79),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        strikes_checked = [c["kalshi_strike"] for c in data["checks"]]
        assert 95000.0 not in strikes_checked


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineEqualStrikes:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_equal_strikes(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.48, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(95000, 0.35, 0.35),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        equal_checks = [c for c in data["checks"] if c["type"] == "Equal"]
        assert len(equal_checks) == 2
        legs = {(c["poly_leg"], c["kalshi_leg"]) for c in equal_checks}
        assert ("Down", "Yes") in legs
        assert ("Up", "No") in legs


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineFeeErosion:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_fee_erosion(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        # Poly Up=0.50, Down=0.48, sum=0.98
        mock_poly.return_value = (_make_poly_data(0.50, 0.48), None)
        # Kalshi market at $96K: poly_strike(95K) < kalshi(96K)
        # Strategy = Poly Up(0.50) + Kalshi No(0.48) = 0.98 → margin=0.02
        # Fees: 0.50*0.02 + 0.52*0.07 = 0.01+0.0364 = 0.0464 > 0.02 → NOT profitable
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(96000, 0.52, 0.48),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()

        for opp in data["opportunities"]:
            assert opp["is_arbitrage"] is True
            assert opp["margin"] > 0
            assert opp["profitable_after_fees"] is False
            assert opp["margin_after_fees"] < 0


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineMultipleOpportunities:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_multiple_opportunities(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.48, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(94000, 0.42, 0.58),
            _make_kalshi_market(94500, 0.38, 0.62),
            _make_kalshi_market(95000, 0.35, 0.35),
        ]), None)

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["opportunities"]) >= 2


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineMarketWindow:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_market_selection_window(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        markets = [_make_kalshi_market(90000 + i*500, 0.52, 0.49) for i in range(20)]
        mock_poly.return_value = (_make_poly_data(0.55, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data(markets), None)

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["checks"]) <= 11


@pytest.mark.integration
class TestCliBotFullPipeline:
    @patch('arbitrage_bot.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_cli_bot_full_pipeline(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (_make_poly_data(0.48, 0.47), None)
        mock_kalshi.return_value = (_make_kalshi_data([
            _make_kalshi_market(94000, 0.42, 0.58),
        ]), None)

        from arbitrage_bot import check_arbitrage
        await check_arbitrage()

        captured = capsys.readouterr()
        assert "Scanning for arbitrage" in captured.out
        assert "POLYMARKET" in captured.out
        assert "ARBITRAGE FOUND" in captured.out
        assert "Est. Fees" in captured.out


@pytest.mark.integration
@patch('api.get_binance_current_price', new_callable=AsyncMock, return_value=(95500.0, None))
class TestFullPipelineTimeout:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_full_pipeline_timeout_handling(self, mock_session, mock_poly, mock_kalshi, mock_binance, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (None, "Connection timed out")
        mock_kalshi.return_value = (None, "Connection timed out")

        resp = await client.get("/arbitrage")
        data = resp.json()

        assert resp.status_code == 200
        assert len(data["errors"]) > 0
        assert data["checks"] == []
