"""Shared arbitrage detection logic.

Contains fee estimation and the core comparison engine used by both
api.py (FastAPI) and arbitrage_bot.py (CLI).
"""
import math
from config import POLYMARKET_FEE_MULTIPLIER, KALSHI_FEE_MULTIPLIER


def estimate_fees(poly_cost: float, kalshi_cost: float) -> float:
    """Estimate trading fees for both legs using parabolic fee formulas.

    Polymarket: multiplier * price * (1 - price)
    Kalshi: ceil_to_cent(multiplier * price * (1 - price))
    """
    poly_pq = poly_cost * (1.0 - poly_cost)
    poly_fee = POLYMARKET_FEE_MULTIPLIER * poly_pq if poly_pq > 0 else 0.0

    kalshi_pq = kalshi_cost * (1.0 - kalshi_cost)
    kalshi_fee = math.ceil(KALSHI_FEE_MULTIPLIER * kalshi_pq * 100) / 100 if kalshi_pq > 0 else 0.0

    return round(poly_fee + kalshi_fee, 4)


def add_fee_info(check: dict) -> None:
    """Mutate an arbitrage check dict to include fee estimation fields."""
    est_fees = estimate_fees(check["poly_cost"], check["kalshi_cost"])
    check["estimated_fees"] = est_fees
    check["margin_after_fees"] = round(check["margin"] - est_fees, 4)
    check["profitable_after_fees"] = check["margin_after_fees"] > 0


def run_arbitrage_checks(poly_strike, poly_up_cost, poly_down_cost, kalshi_markets):
    """
    Compare Polymarket and Kalshi prices to find arbitrage opportunities.

    Returns (checks_list, opportunities_list).
    """
    checks = []
    opportunities = []

    for km in kalshi_markets:
        kalshi_strike = km["strike"]
        kalshi_yes_cost = km["yes_ask"]
        kalshi_no_cost = km["no_ask"]

        check_data = {
            "kalshi_strike": kalshi_strike,
            "kalshi_yes": kalshi_yes_cost,
            "kalshi_no": kalshi_no_cost,
            "type": "",
            "poly_leg": "",
            "kalshi_leg": "",
            "poly_cost": 0,
            "kalshi_cost": 0,
            "total_cost": 0,
            "is_arbitrage": False,
            "margin": 0,
        }

        if poly_strike > kalshi_strike:
            # Only need kalshi_yes — skip if no quote
            if kalshi_yes_cost == 0:
                continue
            check_data["type"] = "Poly > Kalshi"
            check_data["poly_leg"] = "Down"
            check_data["kalshi_leg"] = "Yes"
            check_data["poly_cost"] = poly_down_cost
            check_data["kalshi_cost"] = kalshi_yes_cost
            check_data["total_cost"] = poly_down_cost + kalshi_yes_cost

        elif poly_strike < kalshi_strike:
            # Only need kalshi_no — skip if no quote
            if kalshi_no_cost == 0:
                continue
            check_data["type"] = "Poly < Kalshi"
            check_data["poly_leg"] = "Up"
            check_data["kalshi_leg"] = "No"
            check_data["poly_cost"] = poly_up_cost
            check_data["kalshi_cost"] = kalshi_no_cost
            check_data["total_cost"] = poly_up_cost + kalshi_no_cost

        elif poly_strike == kalshi_strike:
            # Check 1: Down + Yes (skip if kalshi_yes has no quote)
            if kalshi_yes_cost != 0:
                check1 = check_data.copy()
                check1["type"] = "Equal"
                check1["poly_leg"] = "Down"
                check1["kalshi_leg"] = "Yes"
                check1["poly_cost"] = poly_down_cost
                check1["kalshi_cost"] = kalshi_yes_cost
                check1["total_cost"] = poly_down_cost + kalshi_yes_cost

                if check1["total_cost"] < 1.00:
                    check1["is_arbitrage"] = True
                    check1["margin"] = 1.00 - check1["total_cost"]
                    add_fee_info(check1)
                    opportunities.append(check1)
                checks.append(check1)

            # Check 2: Up + No (skip if kalshi_no has no quote)
            if kalshi_no_cost != 0:
                check2 = check_data.copy()
                check2["type"] = "Equal"
                check2["poly_leg"] = "Up"
                check2["kalshi_leg"] = "No"
                check2["poly_cost"] = poly_up_cost
                check2["kalshi_cost"] = kalshi_no_cost
                check2["total_cost"] = poly_up_cost + kalshi_no_cost

                if check2["total_cost"] < 1.00:
                    check2["is_arbitrage"] = True
                    check2["margin"] = 1.00 - check2["total_cost"]
                    add_fee_info(check2)
                    opportunities.append(check2)
                checks.append(check2)
            continue  # Skip adding base check_data

        if check_data["total_cost"] < 1.00:
            check_data["is_arbitrage"] = True
            check_data["margin"] = 1.00 - check_data["total_cost"]
            add_fee_info(check_data)
            opportunities.append(check_data)

        checks.append(check_data)

    return checks, opportunities
