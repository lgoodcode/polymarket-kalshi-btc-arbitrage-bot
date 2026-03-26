"""CLI arbitrage bot with async polling.

Continuously scans for arbitrage opportunities and prints results.
Uses the shared arbitrage engine from arbitrage.py.
"""
import asyncio
import datetime
import logging
import uuid
from decimal import Decimal

from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct
from arbitrage import estimate_fees, run_arbitrage_checks
from binance import get_binance_current_price
from http_utils import create_session
from config import POLL_INTERVAL, PRICE_SUM_MIN, PRICE_SUM_MAX
from log_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Legacy alias for backward compatibility with tests
_estimate_fees = estimate_fees

ONE = Decimal("1")
ZERO = Decimal("0")


async def check_arbitrage():
    scan_id = str(uuid.uuid4())[:8]
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Scanning for arbitrage... (scan:{scan_id})")

    # Parallel fetch; fetch Binance price once to avoid duplicate calls
    session = await create_session()
    try:
        binance_price = await get_binance_current_price(session)
        (poly_data, poly_err), (kalshi_data, kalshi_err) = await asyncio.gather(
            fetch_polymarket_data_struct(session, binance_price=binance_price),
            fetch_kalshi_data_struct(session, binance_price=binance_price),
        )
    finally:
        await session.close()

    if poly_err:
        print(f"Polymarket Error: {poly_err}")
        logger.error("Scan %s: Polymarket error: %s", scan_id, poly_err)
        return
    if kalshi_err:
        print(f"Kalshi Error: {kalshi_err}")
        logger.error("Scan %s: Kalshi error: %s", scan_id, kalshi_err)
        return

    if not poly_data or not kalshi_data:
        print("Missing data.")
        return

    poly_strike = poly_data["price_to_beat"]
    poly_up_cost = poly_data["prices"].get("Up", ZERO)
    poly_down_cost = poly_data["prices"].get("Down", ZERO)
    poly_depth = poly_data.get("depth", {})
    up_depth = poly_depth.get("Up", 0)
    down_depth = poly_depth.get("Down", 0)

    if poly_strike is None:
        print("Polymarket Strike is None")
        return

    print(f"POLYMARKET | Strike: ${float(poly_strike):,.2f} | Up: ${float(poly_up_cost):.3f} ({float(up_depth):.0f} avail) | Down: ${float(poly_down_cost):.3f} ({float(down_depth):.0f} avail)")

    poly_sum = poly_up_cost + poly_down_cost
    if poly_sum > 0 and (poly_sum < PRICE_SUM_MIN or poly_sum > PRICE_SUM_MAX):
        print(f"WARNING: Polymarket prices may be stale/incorrect: Up + Down = ${float(poly_sum):.3f} (expected ~$1.00)")
        return

    kalshi_markets = kalshi_data["markets"]
    if not kalshi_markets:
        print("No Kalshi markets found")
        return

    found_arb = False

    for km in kalshi_markets:
        kalshi_strike = Decimal(str(km["strike"]))
        kalshi_yes_cost = Decimal(str(km["yes_ask"]))
        kalshi_no_cost = Decimal(str(km["no_ask"]))

        if kalshi_yes_cost == 0 or kalshi_no_cost == 0:
            continue

        if abs(kalshi_strike - poly_strike) < 2500:
            print(f"  KALSHI | Strike: ${float(kalshi_strike):,.2f} | Yes: ${float(kalshi_yes_cost):.2f} | No: ${float(kalshi_no_cost):.2f}")

        if poly_strike > kalshi_strike:
            total_cost = poly_down_cost + kalshi_yes_cost
            print(f"    [Poly > Kalshi] Checking: Poly Down (${float(poly_down_cost):.3f}) + Kalshi Yes (${float(kalshi_yes_cost):.3f}) = ${float(total_cost):.3f}")

            if total_cost < ONE:
                margin = ONE - total_cost
                est_fees = estimate_fees(poly_down_cost, kalshi_yes_cost)
                print("!!! ARBITRAGE FOUND !!!")
                print(f"Type: Poly Strike ({poly_strike}) > Kalshi Strike ({kalshi_strike})")
                print("Strategy: Buy Poly DOWN + Kalshi YES")
                print(f"Total Cost: ${float(total_cost):.3f}")
                print("Min Payout: $1.00")
                print(f"Risk-Free Profit: ${float(margin):.3f} per unit")
                print(f"Est. Fees: ${float(est_fees):.4f} | After Fees: ${float(margin - est_fees):.4f} {'(PROFITABLE)' if margin > est_fees else '(NOT PROFITABLE)'}")
                logger.info("Scan %s: ARB FOUND Poly>Kalshi cost=%.3f margin=%.3f", scan_id, float(total_cost), float(margin))
                found_arb = True

        elif poly_strike < kalshi_strike:
            total_cost = poly_up_cost + kalshi_no_cost
            print(f"    [Poly < Kalshi] Checking: Poly Up (${float(poly_up_cost):.3f}) + Kalshi No (${float(kalshi_no_cost):.3f}) = ${float(total_cost):.3f}")

            if total_cost < ONE:
                margin = ONE - total_cost
                est_fees = estimate_fees(poly_up_cost, kalshi_no_cost)
                print("!!! ARBITRAGE FOUND !!!")
                print(f"Type: Poly Strike ({poly_strike}) < Kalshi Strike ({kalshi_strike})")
                print("Strategy: Buy Poly UP + Kalshi NO")
                print(f"Total Cost: ${float(total_cost):.3f}")
                print("Min Payout: $1.00")
                print(f"Risk-Free Profit: ${float(margin):.3f} per unit")
                print(f"Est. Fees: ${float(est_fees):.4f} | After Fees: ${float(margin - est_fees):.4f} {'(PROFITABLE)' if margin > est_fees else '(NOT PROFITABLE)'}")
                logger.info("Scan %s: ARB FOUND Poly<Kalshi cost=%.3f margin=%.3f", scan_id, float(total_cost), float(margin))
                found_arb = True

        elif poly_strike == kalshi_strike:
            cost1 = poly_down_cost + kalshi_yes_cost
            print(f"    [Poly == Kalshi] Checking: Poly Down (${float(poly_down_cost):.3f}) + Kalshi Yes (${float(kalshi_yes_cost):.3f}) = ${float(cost1):.3f}")

            if cost1 < ONE:
                margin = ONE - cost1
                est_fees = estimate_fees(poly_down_cost, kalshi_yes_cost)
                print("!!! ARBITRAGE FOUND !!!")
                print(f"Type: Equal Strikes ({poly_strike})")
                print("Strategy: Buy Poly DOWN + Kalshi YES")
                print(f"Total Cost: ${float(cost1):.3f}")
                print(f"Risk-Free Profit: ${float(margin):.3f} per unit")
                print(f"Est. Fees: ${float(est_fees):.4f} | After Fees: ${float(margin - est_fees):.4f} {'(PROFITABLE)' if margin > est_fees else '(NOT PROFITABLE)'}")
                found_arb = True

            cost2 = poly_up_cost + kalshi_no_cost
            print(f"    [Poly == Kalshi] Checking: Poly Up (${float(poly_up_cost):.3f}) + Kalshi No (${float(kalshi_no_cost):.3f}) = ${float(cost2):.3f}")

            if cost2 < ONE:
                margin = ONE - cost2
                est_fees = estimate_fees(poly_up_cost, kalshi_no_cost)
                print("!!! ARBITRAGE FOUND !!!")
                print(f"Type: Equal Strikes ({poly_strike})")
                print("Strategy: Buy Poly UP + Kalshi NO")
                print(f"Total Cost: ${float(cost2):.3f}")
                print(f"Risk-Free Profit: ${float(margin):.3f} per unit")
                print(f"Est. Fees: ${float(est_fees):.4f} | After Fees: ${float(margin - est_fees):.4f} {'(PROFITABLE)' if margin > est_fees else '(NOT PROFITABLE)'}")
                found_arb = True

    if not found_arb:
        print("No risk-free arbitrage found.")
    print("-" * 50)


def main():
    print("Starting Arbitrage Bot...")
    print("Press Ctrl+C to stop.")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try:
            loop.run_until_complete(check_arbitrage())
            loop.run_until_complete(asyncio.sleep(POLL_INTERVAL))
        except KeyboardInterrupt:
            print("\nStopping...")
            break
        except Exception as e:
            print(f"Error: {e}")
            logger.exception("Unexpected error in main loop")
            loop.run_until_complete(asyncio.sleep(POLL_INTERVAL))
    loop.close()


if __name__ == "__main__":
    main()
