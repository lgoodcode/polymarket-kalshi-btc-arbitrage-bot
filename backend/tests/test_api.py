import datetime
import pytz
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from api import app, _estimate_fees, _add_fee_info

UTC = pytz.utc
client = TestClient(app)


# --- _estimate_fees tests ---

class TestEstimateFees:
    def test_both_half(self):
        # poly: (1-0.50)*0.02=0.01, kalshi: (1-0.50)*0.07=0.035
        result = _estimate_fees(0.50, 0.50)
        assert result == 0.045

    def test_both_zero_cost(self):
        # Maximum profit → maximum fees
        result = _estimate_fees(0.0, 0.0)
        assert result == 0.09  # 1.0*0.02 + 1.0*0.07

    def test_both_at_one(self):
        # No profit → no fees
        result = _estimate_fees(1.0, 1.0)
        assert result == 0.0

    def test_one_at_one(self):
        result = _estimate_fees(1.0, 0.50)
        assert result == 0.035  # Only kalshi fee

    def test_typical_arb_costs(self):
        # poly_down=0.48, kalshi_yes=0.51
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
        assert len(check) == 6  # 3 original + 3 added


# --- get_arbitrage_data endpoint tests ---

class TestGetArbitrageData:
    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_poly_error(self, mock_poly, mock_kalshi):
        mock_poly.return_value = (None, "Polymarket API down")
        mock_kalshi.return_value = ({"event_ticker": "TEST", "current_price": 100.0, "markets": []}, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        assert resp.status_code == 200
        assert "Polymarket API down" in data["errors"]
        assert data["checks"] == []
        assert data["opportunities"] == []

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_kalshi_error(self, mock_poly, mock_kalshi):
        mock_poly.return_value = ({"price_to_beat": 95000.0, "current_price": 95500.0, "prices": {"Up": 0.55, "Down": 0.47}, "slug": "test", "target_time_utc": None}, None)
        mock_kalshi.return_value = (None, "Kalshi API down")

        resp = client.get("/arbitrage")
        data = resp.json()
        assert "Kalshi API down" in data["errors"]

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_both_errors(self, mock_poly, mock_kalshi):
        mock_poly.return_value = (None, "Poly error")
        mock_kalshi.return_value = (None, "Kalshi error")

        resp = client.get("/arbitrage")
        data = resp.json()
        assert len(data["errors"]) == 2

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_poly_strike_none(self, mock_poly, mock_kalshi, sample_kalshi_data):
        mock_poly.return_value = ({
            "price_to_beat": None,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        assert "Polymarket Strike is None" in data["errors"]
        assert data["checks"] == []

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_price_sanity_fail_too_low(self, mock_poly, mock_kalshi, sample_kalshi_data):
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.30, "Down": 0.30},  # Sum = 0.60 < 0.85
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        assert any("sanity check" in e for e in data["errors"])
        assert data["checks"] == []

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_price_sanity_fail_too_high(self, mock_poly, mock_kalshi, sample_kalshi_data):
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.70, "Down": 0.70},  # Sum = 1.40 > 1.15
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        assert any("sanity check" in e for e in data["errors"])

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_price_sanity_pass_normal(self, mock_poly, mock_kalshi, sample_kalshi_data):
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},  # Sum = 1.02, within range
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        assert not any("sanity check" in e for e in data["errors"])
        assert len(data["checks"]) > 0

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_arb_poly_gt_kalshi(self, mock_poly, mock_kalshi):
        """poly_strike > kalshi_strike: Buy Poly Down + Kalshi Yes."""
        mock_poly.return_value = ({
            "price_to_beat": 96000.0,
            "current_price": 96500.0,
            "prices": {"Up": 0.60, "Down": 0.35},  # Sum = 0.95
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # poly_strike(96000) > kalshi_strike(95000): poly_down(0.35) + kalshi_yes(0.42) = 0.77
        assert len(data["opportunities"]) == 1
        opp = data["opportunities"][0]
        assert opp["poly_leg"] == "Down"
        assert opp["kalshi_leg"] == "Yes"
        assert opp["total_cost"] == pytest.approx(0.77, abs=0.01)
        assert opp["margin"] == pytest.approx(0.23, abs=0.01)
        assert opp["is_arbitrage"] is True
        assert "estimated_fees" in opp
        assert "margin_after_fees" in opp

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_arb_poly_lt_kalshi(self, mock_poly, mock_kalshi):
        """poly_strike < kalshi_strike: Buy Poly Up + Kalshi No."""
        mock_poly.return_value = ({
            "price_to_beat": 94000.0,
            "current_price": 94500.0,
            "prices": {"Up": 0.35, "Down": 0.60},  # Sum = 0.95
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # poly_strike(94000) < kalshi_strike(95000): poly_up(0.35) + kalshi_no(0.42) = 0.77
        assert len(data["opportunities"]) == 1
        opp = data["opportunities"][0]
        assert opp["poly_leg"] == "Up"
        assert opp["kalshi_leg"] == "No"
        assert opp["is_arbitrage"] is True

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_arb_equal_strikes_both_combos(self, mock_poly, mock_kalshi):
        """Equal strikes: both combos checked."""
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.45, "Down": 0.47},  # Sum = 0.92, passes sanity
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # Down(0.47) + Yes(0.35) = 0.82 < 1.00 → arb
        # Up(0.45) + No(0.35) = 0.80 < 1.00 → arb
        assert len(data["opportunities"]) == 2
        assert len(data["checks"]) == 2

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_no_arb_total_above_one(self, mock_poly, mock_kalshi):
        """No arb when total_cost >= 1.00."""
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # poly_down(0.47) + kalshi_yes(0.82) = 1.29 ≥ 1.00
        assert len(data["opportunities"]) == 0
        assert len(data["checks"]) == 1
        assert data["checks"][0]["is_arbitrage"] is False

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_no_arb_exactly_one(self, mock_poly, mock_kalshi):
        """No arb when total_cost == exactly 1.00 (strict < comparison)."""
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # poly_down(0.50) + kalshi_yes(0.50) = 1.00, NOT < 1.00
        assert len(data["opportunities"]) == 0

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_unpriced_legs_skipped(self, mock_poly, mock_kalshi, sample_kalshi_data_with_unpriced):
        mock_poly.return_value = ({
            "price_to_beat": 95000.0,
            "current_price": 95500.0,
            "prices": {"Up": 0.55, "Down": 0.47},
            "slug": "test",
            "target_time_utc": None,
        }, None)
        mock_kalshi.return_value = (sample_kalshi_data_with_unpriced, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        # Market at 95000 has yes_ask=0, should be skipped
        # Only 94000 and 96000 should be checked
        strikes_checked = [c["kalshi_strike"] for c in data["checks"]]
        assert 95000.0 not in strikes_checked
        assert 94000.0 in strikes_checked
        assert 96000.0 in strikes_checked

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_empty_kalshi_markets(self, mock_poly, mock_kalshi):
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

        resp = client.get("/arbitrage")
        data = resp.json()
        assert data["checks"] == []
        assert data["opportunities"] == []
        assert data["errors"] == []

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_market_selection_window(self, mock_poly, mock_kalshi):
        """Verify closest ±4 market selection."""
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # 20 markets, closest to 95000 is index 10 (95000)
        # Window: [10-4, 10+5] = [6, 15] → up to 9 markets
        # Equal strike generates 2 checks, so total can be slightly higher
        assert len(data["checks"]) <= 11
        assert len(data["checks"]) >= 5  # At least some markets checked

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_fee_info_only_on_opportunities(self, mock_poly, mock_kalshi):
        """Fee info should only be on opportunity dicts, not regular checks."""
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # No arb → no fee info on checks
        for check in data["checks"]:
            assert "estimated_fees" not in check

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_response_structure(self, mock_poly, mock_kalshi, sample_poly_data, sample_kalshi_data):
        mock_poly.return_value = (sample_poly_data, None)
        mock_kalshi.return_value = (sample_kalshi_data, None)

        resp = client.get("/arbitrage")
        data = resp.json()
        assert "timestamp" in data
        assert "polymarket" in data
        assert "kalshi" in data
        assert "checks" in data
        assert "opportunities" in data
        assert "errors" in data

    @patch('api.fetch_kalshi_data_struct')
    @patch('api.fetch_polymarket_data_struct')
    def test_equal_strike_continue_no_double_count(self, mock_poly, mock_kalshi):
        """Equal-strike branch uses continue, so base check_data is not added again."""
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

        resp = client.get("/arbitrage")
        data = resp.json()
        # Equal strikes → 2 checks (Down+Yes and Up+No), NOT 3
        assert len(data["checks"]) == 2
