"""Shared arbitrage detection logic.

Contains fee estimation and the core comparison engine used by both
api.py (FastAPI) and arbitrage_bot.py (CLI).
"""
import math
from decimal import Decimal, ROUND_CEILING
from config import POLYMARKET_FEE_MULTIPLIER, KALSHI_FEE_MULTIPLIER

# Decimal constants
ONE = Decimal("1")
ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
EPSILON = Decimal("1E-9")


def estimate_fees(poly_cost, kalshi_cost) -> Decimal:
    """Estimate trading fees for both legs using parabolic fee formulas.

    Polymarket: multiplier * price * (1 - price)
    Kalshi: ceil_to_cent(multiplier * price * (1 - price))

    Accepts float or Decimal inputs; returns Decimal.
    """
    poly_cost = Decimal(str(poly_cost))
    kalshi_cost = Decimal(str(kalshi_cost))

    poly_pq = poly_cost * (ONE - poly_cost)
    poly_fee = POLYMARKET_FEE_MULTIPLIER * poly_pq if poly_pq > ZERO else ZERO

    kalshi_pq = kalshi_cost * (ONE - kalshi_cost)
    if kalshi_pq > ZERO:
        raw = KALSHI_FEE_MULTIPLIER * kalshi_pq * ONE_HUNDRED - EPSILON
        # ceil to next cent
        kalshi_fee = raw.to_integral_value(rounding=ROUND_CEILING) / ONE_HUNDRED
    else:
        kalshi_fee = ZERO

    return (poly_fee + kalshi_fee).quantize(Decimal("0.0001"))


def add_fee_info(check: dict) -> None:
    """Mutate an arbitrage check dict to include fee estimation fields."""
    est_fees = estimate_fees(check["poly_cost"], check["kalshi_cost"])
    margin = Decimal(str(check["margin"]))
    check["estimated_fees"] = est_fees
    check["margin_after_fees"] = (margin - est_fees).quantize(Decimal("0.0001"))
    check["profitable_after_fees"] = check["margin_after_fees"] > ZERO


def run_arbitrage_checks(poly_strike, poly_up_cost, poly_down_cost, kalshi_markets):
    """
    Compare Polymarket and Kalshi prices to find arbitrage opportunities.

    Accepts float or Decimal inputs. Returns (checks_list, opportunities_list).
    """
    poly_strike = Decimal(str(poly_strike))
    poly_up_cost = Decimal(str(poly_up_cost))
    poly_down_cost = Decimal(str(poly_down_cost))

    checks = []
    opportunities = []

    for km in kalshi_markets:
        kalshi_strike = Decimal(str(km["strike"]))
        kalshi_yes_cost = Decimal(str(km["yes_ask"]))
        kalshi_no_cost = Decimal(str(km["no_ask"]))

        check_data = {
            "kalshi_strike": kalshi_strike,
            "kalshi_yes": kalshi_yes_cost,
            "kalshi_no": kalshi_no_cost,
            "type": "",
            "poly_leg": "",
            "kalshi_leg": "",
            "poly_cost": ZERO,
            "kalshi_cost": ZERO,
            "total_cost": ZERO,
            "is_arbitrage": False,
            "margin": ZERO,
        }

        if poly_strike > kalshi_strike:
            # Only need kalshi_yes — skip if no quote
            if kalshi_yes_cost == ZERO:
                continue
            check_data["type"] = "Poly > Kalshi"
            check_data["poly_leg"] = "Down"
            check_data["kalshi_leg"] = "Yes"
            check_data["poly_cost"] = poly_down_cost
            check_data["kalshi_cost"] = kalshi_yes_cost
            check_data["total_cost"] = poly_down_cost + kalshi_yes_cost

        elif poly_strike < kalshi_strike:
            # Only need kalshi_no — skip if no quote
            if kalshi_no_cost == ZERO:
                continue
            check_data["type"] = "Poly < Kalshi"
            check_data["poly_leg"] = "Up"
            check_data["kalshi_leg"] = "No"
            check_data["poly_cost"] = poly_up_cost
            check_data["kalshi_cost"] = kalshi_no_cost
            check_data["total_cost"] = poly_up_cost + kalshi_no_cost

        elif poly_strike == kalshi_strike:
            # Check 1: Down + Yes (skip if kalshi_yes has no quote)
            if kalshi_yes_cost != ZERO:
                check1 = check_data.copy()
                check1["type"] = "Equal"
                check1["poly_leg"] = "Down"
                check1["kalshi_leg"] = "Yes"
                check1["poly_cost"] = poly_down_cost
                check1["kalshi_cost"] = kalshi_yes_cost
                check1["total_cost"] = poly_down_cost + kalshi_yes_cost

                if check1["total_cost"] < ONE:
                    check1["is_arbitrage"] = True
                    check1["margin"] = ONE - check1["total_cost"]
                    add_fee_info(check1)
                    opportunities.append(check1)
                checks.append(check1)

            # Check 2: Up + No (skip if kalshi_no has no quote)
            if kalshi_no_cost != ZERO:
                check2 = check_data.copy()
                check2["type"] = "Equal"
                check2["poly_leg"] = "Up"
                check2["kalshi_leg"] = "No"
                check2["poly_cost"] = poly_up_cost
                check2["kalshi_cost"] = kalshi_no_cost
                check2["total_cost"] = poly_up_cost + kalshi_no_cost

                if check2["total_cost"] < ONE:
                    check2["is_arbitrage"] = True
                    check2["margin"] = ONE - check2["total_cost"]
                    add_fee_info(check2)
                    opportunities.append(check2)
                checks.append(check2)
            continue  # Skip adding base check_data

        if check_data["total_cost"] < ONE:
            check_data["is_arbitrage"] = True
            check_data["margin"] = ONE - check_data["total_cost"]
            add_fee_info(check_data)
            opportunities.append(check_data)

        checks.append(check_data)

    return checks, opportunities
