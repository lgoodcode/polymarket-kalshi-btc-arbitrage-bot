import datetime
import pytz
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from api import app, _estimate_fees, _add_fee_info

UTC = pytz.utc


# Use httpx AsyncClient for async FastAPI testing
@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- _estimate_fees tests ---

class TestEstimateFees:
    def test_both_half(self):
        result = _estimate_fees(0.50, 0.50)
        assert result == 0.045

    def test_both_zero_cost(self):
        result = _estimate_fees(0.0, 0.0)
        assert result == 0.09

    def test_both_at_one(self):
        result = _estimate_fees(1.0, 1.0)
        assert result == 0.0

    def test_one_at_one(self):
        result = _estimate_fees(1.0, 0.50)
        assert result == 0.035

    def test_typical_arb_costs(self):
        result = _estimate_fees(0.48, 0.51)
        expected = round((0.52 * 0.02) + (0.49 * 0.07), 4)
        assert result == expected

    def test_above_one_no_fees(self):
        result = _estimate_fees(1.5, 1.5)
        assert result == 0.0


# --- _add_fee_info tests ---

class TestAddFeeInfo:
    def test_profitable(self):
        check = {"poly_cost": 0.40, "kalshi_cost": 0.42, "margin": 0.18}
        _add_fee_info(check)
        assert "estimated_fees" in check
        assert "margin_after_fees" in check
        assert check["profitable_after_fees"] is True
        assert check["margin_after_fees"] > 0

    def test_unprofitable(self):
        check = {"poly_cost": 0.48, "kalshi_cost": 0.51, "margin": 0.01}
        _add_fee_info(check)
        assert check["profitable_after_fees"] is False
        assert check["margin_after_fees"] < 0

    def test_mutates_dict(self):
        check = {"poly_cost": 0.50, "kalshi_cost": 0.50, "margin": 0.10}
        _add_fee_info(check)
        assert len(check) == 6


# --- get_arbitrage_data endpoint tests ---

class TestGetArbitrageData:
    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_poly_error(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (None, "Polymarket API down")
        mock_kalshi.return_value = ({"event_ticker": "TEST", "current_price": 100.0, "markets": []}, None)

        # Clear cache
        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert resp.status_code == 200
        assert "Polymarket API down" in data["errors"]
        assert data["checks"] == []
        assert data["opportunities"] == []

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_kalshi_error(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({"price_to_beat": 95000.0, "current_price": 95500.0, "prices": {"Up": 0.55, "Down": 0.47}, "slug": "test", "target_time_utc": None}, None)
        mock_kalshi.return_value = (None, "Kalshi API down")

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert "Kalshi API down" in data["errors"]

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_both_errors(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (None, "Poly error")
        mock_kalshi.return_value = (None, "Kalshi error")

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["errors"]) == 2

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_poly_strike_none(self, mock_session, mock_poly, mock_kalshi, client, sample_kalshi_data):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": None,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert "Polymarket Strike is None" in data["errors"]
        assert data["checks"] == []

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_price_sanity_fail_too_low(self, mock_session, mock_poly, mock_kalshi, client, sample_kalshi_data):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.30, "Down": 0.30},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert any("sanity check" in e for e in data["errors"])
        assert data["checks"] == []

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_price_sanity_fail_too_high(self, mock_session, mock_poly, mock_kalshi, client, sample_kalshi_data):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.70, "Down": 0.70},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert any("sanity check" in e for e in data["errors"])

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_price_sanity_pass_normal(self, mock_session, mock_poly, mock_kalshi, client, sample_kalshi_data):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert not any("sanity check" in e for e in data["errors"])
        assert len(data["checks"]) > 0

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_arb_poly_gt_kalshi(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 96000.0,
            "current_price": 96500.0,
            "prices": {"Up": 0.60, "Down": 0.35},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 96500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.80, "yes_ask": 0.42, "no_bid": 0.15, "no_ask": 0.58, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["opportunities"]) == 1
        opp = data["opportunities"][0]
        assert opp["poly_leg"] == "Down"
        assert opp["kalshi_leg"] == "Yes"
        assert opp["total_cost"] == pytest.approx(0.77, abs=0.01)
        assert opp["margin"] == pytest.approx(0.23, abs=0.01)
        assert opp["is_arbitrage"] is True
        assert "estimated_fees" in opp
        assert "margin_after_fees" in opp

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_arb_poly_lt_kalshi(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 94000.0,
            "current_price": 94500.0,
            "prices": {"Up": 0.35, "Down": 0.60},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 94500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.50, "yes_ask": 0.58, "no_bid": 0.40, "no_ask": 0.42, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["opportunities"]) == 1
        opp = data["opportunities"][0]
        assert opp["poly_leg"] == "Up"
        assert opp["kalshi_leg"] == "No"
        assert opp["is_arbitrage"] is True

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_arb_equal_strikes_both_combos(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.45, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 95500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.30, "yes_ask": 0.35, "no_bid": 0.30, "no_ask": 0.35, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["opportunities"]) == 2
        assert len(data["checks"]) == 2

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_no_arb_total_above_one(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 96000.0,
            "current_price": 96500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 96500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.80, "yes_ask": 0.82, "no_bid": 0.15, "no_ask": 0.18, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["opportunities"]) == 0
        assert len(data["checks"]) == 1
        assert data["checks"][0]["is_arbitrage"] is False

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_no_arb_exactly_one(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 96000.0,
            "current_price": 96500.0,
            "prices": {"Up": 0.50, "Down": 0.50},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 96500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.49, "yes_ask": 0.50, "no_bid": 0.49, "no_ask": 0.50, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["opportunities"]) == 0

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_unpriced_legs_skipped(self, mock_session, mock_poly, mock_kalshi, client, sample_kalshi_data_with_unpriced):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data_with_unpriced, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        strikes_checked = [c["kalshi_strike"] for c in data["checks"]]
        assert 95000.0 not in strikes_checked
        assert 94000.0 in strikes_checked
        assert 96000.0 in strikes_checked

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_empty_kalshi_markets(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 95500.0,
            "markets": []
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert data["checks"] == []
        assert data["opportunities"] == []
        assert data["errors"] == []

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_market_selection_window(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        markets = []
        for i in range(20):
            strike = 90000.0 + (i * 500)
            markets.append({
                "strike": strike,
                "yes_bid": 0.50, "yes_ask": 0.52,
                "no_bid": 0.47, "no_ask": 0.49,
                "subtitle": f"${int(strike):,} or above"
            })

        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 95500.0,
            "markets": markets
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["checks"]) <= 11
        assert len(data["checks"]) >= 5

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_fee_info_only_on_opportunities(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 96000.0,
            "current_price": 96500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 96500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.80, "yes_ask": 0.82, "no_bid": 0.15, "no_ask": 0.18, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        for check in data["checks"]:
            assert "estimated_fees" not in check

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_response_structure(self, mock_session, mock_poly, mock_kalshi, client, sample_poly_data, sample_kalshi_data):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (sample_poly_data, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert "timestamp" in data
        assert "polymarket" in data
        assert "kalshi" in data
        assert "checks" in data
        assert "opportunities" in data
        assert "errors" in data
        assert "scan_id" in data
        assert "fee_disclaimer" in data

    @patch('api.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('api.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('api.create_session', new_callable=AsyncMock)
    async def test_equal_strike_continue_no_double_count(self, mock_session, mock_poly, mock_kalshi, client):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST",
            "current_price": 95500.0,
            "markets": [
                {"strike": 95000.0, "yes_bid": 0.50, "yes_ask": 0.52, "no_bid": 0.47, "no_ask": 0.49, "subtitle": "$95,000 or above"},
            ]
        }, None)

        from api import _cache
        _cache["data"] = None; _cache["timestamp"] = 0.0

        resp = await client.get("/arbitrage")
        data = resp.json()
        assert len(data["checks"]) == 2
