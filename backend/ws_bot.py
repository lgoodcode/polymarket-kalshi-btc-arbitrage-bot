"""WebSocket-based arbitrage bot with real-time streaming.

Replaces the 5-second HTTP polling loop with event-driven WebSocket
connections to Polymarket and Kalshi. Falls back to HTTP polling if
WebSocket connections fail.

Usage: python ws_bot.py
"""
import asyncio
import datetime
import json
import logging
import uuid
from decimal import Decimal

from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct, get_kalshi_markets
from arbitrage import estimate_fees
from binance import get_binance_current_price, get_binance_open_price
from http_utils import create_session, fetch_json
from get_current_markets import get_current_market_urls
from config import (
    POLL_INTERVAL,
    PRICE_SUM_MIN,
    PRICE_SUM_MAX,
    POLYMARKET_GAMMA_URL,
    EXECUTION_ENABLED,
    WS_FALLBACK_TO_HTTP,
)
from log_config import setup_logging
from websocket.manager import WebSocketManager

setup_logging()
logger = logging.getLogger(__name__)

ONE = Decimal("1")
ZERO = Decimal("0")


async def resolve_poly_token_ids(session, slug: str) -> tuple[dict | None, str | None]:
    """Fetch Polymarket token IDs for the given market slug.

    Returns ({"Up": token_id, "Down": token_id}, None) or (None, error).
    """
    try:
        data = await fetch_json(session, POLYMARKET_GAMMA_URL, params={"slug": slug})
        if not data:
            return None, "Event not found"

        event = data[0]
        markets = event.get("markets", [])
        if not markets:
            return None, "No markets in event"

        market = markets[0]
        clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))
        outcomes = json.loads(market.get("outcomes", "[]"))

        if len(clob_token_ids) != 2 or len(outcomes) != len(clob_token_ids):
            return None, f"Unexpected token/outcome count: {len(clob_token_ids)}/{len(outcomes)}"

        token_map = {}
        for outcome, token_id in zip(outcomes, clob_token_ids):
            token_map[outcome] = token_id

        return token_map, None
    except Exception as e:
        return None, str(e)


async def resolve_kalshi_tickers(session, event_ticker: str) -> tuple[list | None, str | None]:
    """Fetch Kalshi market tickers for the given event.

    Returns (list_of_ticker_strings, None) or (None, error).
    """
    try:
        markets, err = await get_kalshi_markets(session, event_ticker)
        if err:
            return None, err
        tickers = [m.get("ticker", "") for m in (markets or []) if m.get("ticker")]
        return tickers, None
    except Exception as e:
        return None, str(e)


def format_opportunity(check: dict) -> str:
    """Format a single arbitrage opportunity for console output."""
    lines = []
    lines.append("!!! ARBITRAGE FOUND !!!")
    lines.append(f"  Type: {check['type']} (Kalshi strike: {check['kalshi_strike']})")
    lines.append(f"  Strategy: Buy Poly {check['poly_leg']} + Kalshi {check['kalshi_leg']}")
    lines.append(f"  Total Cost: ${float(check['total_cost']):.3f}")
    lines.append(f"  Margin: ${float(check['margin']):.3f}")
    if "estimated_fees" in check:
        lines.append(
            f"  Est. Fees: ${float(check['estimated_fees']):.4f} | "
            f"After Fees: ${float(check['margin_after_fees']):.4f} "
            f"{'(PROFITABLE)' if check.get('profitable_after_fees') else '(NOT PROFITABLE)'}"
        )
    return "\n".join(lines)


async def on_opportunity(checks: list[dict], opportunities: list[dict]) -> None:
    """Callback for WebSocketManager — print detected opportunities."""
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if opportunities:
        for opp in opportunities:
            print(f"[{ts}] {format_opportunity(opp)}")
            logger.info("WS ARB: type=%s total_cost=%.3f margin=%.3f",
                        opp["type"], float(opp["total_cost"]), float(opp["margin"]))
    else:
        # Periodic status (only log, don't flood console)
        logger.debug("WS scan: %d checks, 0 opportunities", len(checks))


async def fallback_poll_loop() -> None:
    """Fallback to HTTP polling if WebSocket connections fail."""
    print("Falling back to HTTP polling mode...")
    logger.warning("WebSocket connections failed, using HTTP polling fallback")

    while True:
        try:
            scan_id = str(uuid.uuid4())[:8]
            print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] HTTP poll scan (scan:{scan_id})")

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
                print(f"  Polymarket Error: {poly_err}")
                continue
            if kalshi_err:
                print(f"  Kalshi Error: {kalshi_err}")
                continue

            if poly_data and kalshi_data:
                from arbitrage import run_arbitrage_checks
                poly_strike = poly_data.get("price_to_beat")
                if poly_strike:
                    checks, opportunities = run_arbitrage_checks(
                        poly_strike,
                        poly_data["prices"].get("Up", ZERO),
                        poly_data["prices"].get("Down", ZERO),
                        kalshi_data["markets"],
                    )
                    if opportunities:
                        for opp in opportunities:
                            print(format_opportunity(opp))
                    else:
                        print("  No arbitrage found.")
        except Exception as e:
            logger.exception("HTTP fallback error: %s", e)

        await asyncio.sleep(POLL_INTERVAL)


async def run_ws_bot() -> None:
    """Main entry point — resolve market data, connect WebSockets, run until Ctrl+C."""
    print("Starting WebSocket Arbitrage Bot...")
    print("Resolving current markets...")

    # Step 1: Resolve market info via HTTP
    market_info = get_current_market_urls()
    slug = market_info["polymarket"].split("/")[-1]
    kalshi_url = market_info["kalshi"]
    event_ticker = kalshi_url.split("/")[-1].upper()

    session = await create_session()
    try:
        # Fetch Binance price, Polymarket tokens, and Kalshi tickers in parallel
        binance_result, poly_tokens_result, kalshi_tickers_result = await asyncio.gather(
            get_binance_current_price(session),
            resolve_poly_token_ids(session, slug),
            resolve_kalshi_tickers(session, event_ticker),
        )

        current_price, price_err = binance_result
        poly_token_ids, poly_tok_err = poly_tokens_result
        kalshi_tickers, kalshi_tick_err = kalshi_tickers_result

        # Also fetch Polymarket strike (price_to_beat) via Binance open price
        target_time_utc = market_info["target_time_utc"]
        poly_strike, strike_err = await get_binance_open_price(session, target_time_utc)
    finally:
        await session.close()

    if poly_tok_err:
        print(f"Error resolving Polymarket tokens: {poly_tok_err}")
        if WS_FALLBACK_TO_HTTP:
            await fallback_poll_loop()
        return

    if kalshi_tick_err:
        print(f"Error resolving Kalshi tickers: {kalshi_tick_err}")
        if WS_FALLBACK_TO_HTTP:
            await fallback_poll_loop()
        return

    if poly_strike is None:
        print(f"Error fetching Polymarket strike price: {strike_err}")
        if WS_FALLBACK_TO_HTTP:
            await fallback_poll_loop()
        return

    print(f"Polymarket slug: {slug}")
    print(f"Polymarket tokens: {poly_token_ids}")
    print(f"Kalshi event: {event_ticker} ({len(kalshi_tickers or [])} markets)")
    print(f"Strike price: ${float(poly_strike):,.2f}")
    if current_price:
        print(f"BTC current price: ${float(current_price):,.2f}")
    print("-" * 50)
    print("Connecting WebSockets...")

    # Step 2: Create and start WebSocket manager
    manager = WebSocketManager(
        poly_token_ids=poly_token_ids,
        kalshi_market_tickers=kalshi_tickers or [],
        poly_strike=poly_strike,
        on_opportunity=on_opportunity,
        authenticated=EXECUTION_ENABLED,
    )

    success, err = await manager.start()
    if not success:
        print(f"WebSocket connection failed: {err}")
        if WS_FALLBACK_TO_HTTP:
            await fallback_poll_loop()
        return

    status = manager.get_status()
    print(f"Polymarket WS: {'connected' if status['polymarket_connected'] else 'DISCONNECTED'}")
    print(f"Kalshi WS: {'connected' if status['kalshi_connected'] else 'DISCONNECTED'}"
          f"{' (authenticated)' if status['kalshi_authenticated'] else ''}")
    print("Listening for real-time updates... (Ctrl+C to stop)")
    print("=" * 50)

    # Step 3: Run until interrupted
    try:
        while manager.running:
            await asyncio.sleep(1)
            # Periodic status logging
            s = manager.get_status()
            if not s["polymarket_connected"] and not s["kalshi_connected"]:
                logger.error("Both WebSocket connections lost")
                break
    except asyncio.CancelledError:
        pass
    finally:
        await manager.stop()
        print(f"\nStopped. Total scans: {manager.get_status()['scan_count']}")


def main():
    print("WebSocket Arbitrage Bot")
    print("Press Ctrl+C to stop.\n")
    try:
        asyncio.run(run_ws_bot())
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
