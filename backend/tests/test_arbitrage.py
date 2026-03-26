"""Tests for the shared arbitrage module."""
import pytest
from decimal import Decimal
from arbitrage import estimate_fees, add_fee_info, run_arbitrage_checks


class TestEstimateFees:
    def test_both_half(self):
        # poly: 0.0624 * 0.5 * 0.5 = 0.0156, kalshi: ceil(0.07 * 0.25 * 100)/100 = 0.02
        result = estimate_fees(0.50, 0.50)
        assert result == Decimal("0.0356")

    def test_both_zero_cost(self):
        # p*(1-p) = 0 for both → no fees
        result = estimate_fees(0.0, 0.0)
        assert result == Decimal("0.0000")

    def test_both_at_one(self):
        result = estimate_fees(1.0, 1.0)
        assert result == Decimal("0.0000")

    def test_one_at_one(self):
        # poly: 0 (p=1), kalshi: ceil(0.07 * 0.5 * 0.5 * 100)/100 = 0.02
        result = estimate_fees(1.0, 0.50)
        assert result == Decimal("0.0200")

    def test_typical_arb_costs(self):
        # poly: 0.0624 * 0.48 * 0.52, kalshi: ceil(0.07 * 0.51 * 0.49 * 100)/100
        result = estimate_fees(0.48, 0.51)
        from decimal import ROUND_CEILING
        expected_poly = Decimal("0.0624") * Decimal("0.48") * Decimal("0.52")
        raw = Decimal("0.07") * Decimal("0.51") * Decimal("0.49") * Decimal("100") - Decimal("1E-9")
        expected_kalshi = raw.to_integral_value(rounding=ROUND_CEILING) / Decimal("100")
        expected = (expected_poly + expected_kalshi).quantize(Decimal("0.0001"))
        assert result == expected

    def test_above_one_no_fees(self):
        result = estimate_fees(1.5, 1.5)
        assert result == Decimal("0.0000")


class TestAddFeeInfo:
    def test_profitable(self):
        check = {"poly_cost": 0.40, "kalshi_cost": 0.42, "margin": 0.18}
        add_fee_info(check)
        assert "estimated_fees" in check
        assert "margin_after_fees" in check
        assert isinstance(check["estimated_fees"], Decimal)
        assert isinstance(check["margin_after_fees"], Decimal)
        assert check["profitable_after_fees"] is True
        assert check["margin_after_fees"] > Decimal("0")

    def test_unprofitable(self):
        check = {"poly_cost": 0.48, "kalshi_cost": 0.51, "margin": 0.01}
        add_fee_info(check)
        assert check["profitable_after_fees"] is False
        assert check["margin_after_fees"] < Decimal("0")

    def test_mutates_dict(self):
        check = {"poly_cost": 0.50, "kalshi_cost": 0.50, "margin": 0.10}
        add_fee_info(check)
        assert len(check) == 6


class TestRunArbitrageChecks:
    def test_poly_gt_kalshi_arb(self):
        markets = [{"strike": 94000.0, "yes_ask": 0.42, "no_ask": 0.58, "yes_bid": 0.40, "no_bid": 0.55, "subtitle": "$94,000"}]
        checks, opps = run_arbitrage_checks(96000.0, 0.60, 0.35, markets)
        assert len(opps) == 1
        assert opps[0]["poly_leg"] == "Down"
        assert opps[0]["kalshi_leg"] == "Yes"
        assert float(opps[0]["total_cost"]) == pytest.approx(0.77, abs=0.01)

    def test_poly_lt_kalshi_arb(self):
        markets = [{"strike": 95000.0, "yes_ask": 0.58, "no_ask": 0.42, "yes_bid": 0.50, "no_bid": 0.40, "subtitle": "$95,000"}]
        checks, opps = run_arbitrage_checks(94000.0, 0.35, 0.60, markets)
        assert len(opps) == 1
        assert opps[0]["poly_leg"] == "Up"
        assert opps[0]["kalshi_leg"] == "No"

    def test_equal_strikes_both_combos(self):
        markets = [{"strike": 95000.0, "yes_ask": 0.35, "no_ask": 0.35, "yes_bid": 0.30, "no_bid": 0.30, "subtitle": "$95,000"}]
        checks, opps = run_arbitrage_checks(95000.0, 0.45, 0.47, markets)
        assert len(checks) == 2
        assert len(opps) == 2

    def test_no_arb(self):
        markets = [{"strike": 95000.0, "yes_ask": 0.82, "no_ask": 0.80, "yes_bid": 0.80, "no_bid": 0.78, "subtitle": "$95,000"}]
        checks, opps = run_arbitrage_checks(96000.0, 0.55, 0.47, markets)
        assert len(opps) == 0
        assert checks[0]["is_arbitrage"] is False

    def test_unpriced_skipped(self):
        markets = [{"strike": 95000.0, "yes_ask": 0, "no_ask": 0, "yes_bid": 0, "no_bid": 0, "subtitle": "$95,000"}]
        checks, opps = run_arbitrage_checks(95000.0, 0.40, 0.40, markets)
        assert len(checks) == 0
        assert len(opps) == 0
