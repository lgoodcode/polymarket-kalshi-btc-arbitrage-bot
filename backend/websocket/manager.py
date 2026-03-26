"""WebSocket connection manager — orchestrates both WS clients.

Coordinates Polymarket and Kalshi WebSocket connections, triggers arbitrage
scans when either side updates, and falls back to HTTP polling on failure.
"""
import asyncio
import logging
import time
from decimal import Decimal

from arbitrage import run_arbitrage_checks
from config import (
    WS_SCAN_INTERVAL,
    WS_FALLBACK_TO_HTTP,
    PRICE_SUM_MIN,
    PRICE_SUM_MAX,
)
from websocket.polymarket_ws import PolymarketWebSocket
from websocket.kalshi_ws import KalshiWebSocket

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")


class WebSocketManager:
    """Orchestrates Polymarket and Kalshi WebSocket connections.

    Event-driven: when either side publishes an update, triggers an
    arbitrage scan using the shared engine from arbitrage.py.

    Args:
        poly_token_ids: Dict mapping outcome to token ID {"Up": "...", "Down": "..."}.
        kalshi_market_tickers: List of Kalshi market ticker strings.
        poly_strike: Decimal strike price for Polymarket.
        on_opportunity: Async callback(checks, opportunities) for detected opportunities.
        on_fill: Async callback(fill_data) for execution fill notifications.
        authenticated: Whether to authenticate Kalshi WS for fills.
    """

    def __init__(
        self,
        poly_token_ids: dict[str, str],
        kalshi_market_tickers: list[str],
        poly_strike: Decimal,
        on_opportunity=None,
        on_fill=None,
        authenticated: bool = False,
    ):
        self._poly_strike = poly_strike
        self._on_opportunity = on_opportunity
        self._authenticated = authenticated

        # Current prices — updated by WS callbacks
        self._poly_prices: dict[str, Decimal] = {}
        self._poly_depth: dict[str, Decimal] = {}
        self._kalshi_markets: list[dict] = []

        # Scan throttle
        self._last_scan_time = 0.0
        self._scan_count = 0

        # Create WS clients
        self._poly_ws = PolymarketWebSocket(
            token_ids=poly_token_ids,
            on_update=self._on_poly_update,
        )
        self._kalshi_ws = KalshiWebSocket(
            on_update=self._on_kalshi_update,
            on_fill=on_fill,
        )
        self._kalshi_market_tickers = kalshi_market_tickers

        self._running = False
        self._fallback_task = None

    async def start(self) -> tuple[bool, str | None]:
        """Start both WebSocket connections.

        Returns (success, error) tuple. Partial success (one side connected)
        returns True with a warning logged.
        """
        self._running = True
        errors = []

        # Connect both in parallel
        poly_result, kalshi_result = await asyncio.gather(
            self._poly_ws.connect(),
            self._kalshi_ws.connect(authenticated=self._authenticated),
        )

        poly_ok, poly_err = poly_result
        kalshi_ok, kalshi_err = kalshi_result

        if poly_err:
            errors.append(f"Polymarket: {poly_err}")
            logger.error("Polymarket WS failed to connect: %s", poly_err)
        if kalshi_err:
            errors.append(f"Kalshi: {kalshi_err}")
            logger.error("Kalshi WS failed to connect: %s", kalshi_err)

        # Subscribe Kalshi to market tickers
        if kalshi_ok and self._kalshi_market_tickers:
            sub_ok, sub_err = await self._kalshi_ws.subscribe_market(self._kalshi_market_tickers)
            if sub_err:
                errors.append(f"Kalshi subscribe: {sub_err}")

            # Subscribe to fills if authenticated
            if self._authenticated and self._kalshi_ws.authenticated:
                await self._kalshi_ws.subscribe_fills()

        if not poly_ok and not kalshi_ok:
            self._running = False
            return False, "; ".join(errors)

        if errors:
            logger.warning("WebSocket manager started with errors: %s", "; ".join(errors))

        return True, None

    async def stop(self) -> None:
        """Stop both WebSocket connections and any fallback tasks."""
        self._running = False
        if self._fallback_task and not self._fallback_task.done():
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except asyncio.CancelledError:
                pass

        await asyncio.gather(
            self._poly_ws.disconnect(),
            self._kalshi_ws.disconnect(),
        )
        logger.info("WebSocket manager stopped (total scans: %d)", self._scan_count)

    async def _on_poly_update(self, prices: dict, depth: dict) -> None:
        """Callback from Polymarket WS — update local state and trigger scan."""
        self._poly_prices = prices
        self._poly_depth = depth
        await self._maybe_run_scan()

    async def _on_kalshi_update(self, markets: list[dict]) -> None:
        """Callback from Kalshi WS — update local state and trigger scan."""
        self._kalshi_markets = markets
        await self._maybe_run_scan()

    async def _maybe_run_scan(self) -> None:
        """Run arbitrage scan if enough time has passed since the last scan."""
        now = time.time()
        if now - self._last_scan_time < WS_SCAN_INTERVAL:
            return
        self._last_scan_time = now
        await self._run_arbitrage_scan()

    async def _run_arbitrage_scan(self) -> None:
        """Execute arbitrage comparison using current WebSocket state."""
        # Need data from both sides
        if not self._poly_prices or not self._kalshi_markets:
            return

        poly_up = self._poly_prices.get("Up", ZERO)
        poly_down = self._poly_prices.get("Down", ZERO)

        # Sanity check
        poly_sum = poly_up + poly_down
        if poly_sum > ZERO and (poly_sum < PRICE_SUM_MIN or poly_sum > PRICE_SUM_MAX):
            logger.warning("WS scan: Polymarket prices may be stale (Up+Down=%.3f)", float(poly_sum))
            return

        try:
            checks, opportunities = run_arbitrage_checks(
                self._poly_strike, poly_up, poly_down, self._kalshi_markets
            )
            self._scan_count += 1

            if self._on_opportunity:
                await self._on_opportunity(checks, opportunities)
        except Exception as e:
            logger.error("WS arbitrage scan error: %s", e)

    def get_status(self) -> dict:
        """Return connection status for both WebSocket clients."""
        return {
            "polymarket_connected": self._poly_ws.connected,
            "kalshi_connected": self._kalshi_ws.connected,
            "kalshi_authenticated": self._kalshi_ws.authenticated,
            "scan_count": self._scan_count,
            "poly_last_update": self._poly_ws.last_message_time,
            "kalshi_last_update": self._kalshi_ws.last_message_time,
        }

    @property
    def poly_ws(self) -> PolymarketWebSocket:
        """Access the Polymarket WebSocket client."""
        return self._poly_ws

    @property
    def kalshi_ws(self) -> KalshiWebSocket:
        """Access the Kalshi WebSocket client."""
        return self._kalshi_ws

    @property
    def running(self) -> bool:
        return self._running
