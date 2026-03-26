"""Kalshi WebSocket client for real-time market data.

Connects to the Kalshi trade API WebSocket for ticker updates and
optionally authenticates for fill notifications.
"""
import asyncio
import json
import logging
import time
from decimal import Decimal

import websockets

from config import (
    WS_KALSHI_URL,
    WS_RECONNECT_BASE_DELAY,
    WS_RECONNECT_MAX_DELAY,
    WS_RECONNECT_MAX_RETRIES,
    WS_HEARTBEAT_INTERVAL,
    KALSHI_API_KEY_ID,
    KALSHI_PRIVATE_KEY_PATH,
)
from websocket.order_book import MarketState, ZERO

logger = logging.getLogger(__name__)


class KalshiWebSocket:
    """Real-time market data client for Kalshi.

    Subscribes to ticker channels for market price updates. Optionally
    authenticates with RSA-PSS to receive fill notifications.

    Args:
        on_update: Async callback(markets) fired when any market price changes.
        on_fill: Async callback(fill_data) fired on fill notifications (auth required).
    """

    def __init__(self, on_update=None, on_fill=None):
        self._on_update = on_update
        self._on_fill = on_fill
        self._market_state = MarketState()
        self._ws = None
        self._running = False
        self._authenticated = False
        self._listen_task = None
        self._heartbeat_task = None
        self._msg_id = 0
        self._last_message_time = 0.0
        # Track subscribed tickers for resubscription on reconnect
        self._subscribed_tickers: list[str] = []
        self._subscribed_event_ticker: str | None = None

    def _next_msg_id(self) -> int:
        """Return an incrementing message ID for the Kalshi WS protocol."""
        self._msg_id += 1
        return self._msg_id

    async def connect(self, authenticated: bool = False) -> tuple[bool, str | None]:
        """Connect to Kalshi WebSocket.

        Args:
            authenticated: If True, attempt login for fill notifications.

        Returns (success, error) tuple.
        """
        try:
            self._ws = await websockets.connect(WS_KALSHI_URL)
            self._running = True
            self._last_message_time = time.time()
            logger.info("Kalshi WS connected")

            # Authenticate if requested and credentials are available
            if authenticated:
                auth_ok, auth_err = await self._authenticate()
                if not auth_ok:
                    logger.warning("Kalshi WS auth failed: %s (continuing unauthenticated)", auth_err)
                else:
                    self._authenticated = True
                    logger.info("Kalshi WS authenticated")

            # Start background tasks
            self._listen_task = asyncio.ensure_future(self._listen())
            self._heartbeat_task = asyncio.ensure_future(self._send_heartbeat())

            return True, None
        except Exception as e:
            logger.error("Kalshi WS connect failed: %s", e)
            return False, str(e)

    async def _authenticate(self) -> tuple[bool, str | None]:
        """Send login command using RSA-PSS signed credentials."""
        if not KALSHI_API_KEY_ID or not KALSHI_PRIVATE_KEY_PATH:
            return False, "Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PATH"

        try:
            from execution.kalshi_auth import (
                load_private_key,
                sign_request,
                get_current_timestamp,
            )

            key, key_err = load_private_key(KALSHI_PRIVATE_KEY_PATH)
            if key_err:
                return False, key_err

            timestamp = get_current_timestamp()
            # Kalshi WS auth signs: timestamp + GET + /trade-api/ws/v2
            sig, sig_err = sign_request(key, timestamp, "GET", "/trade-api/ws/v2")
            if sig_err:
                return False, sig_err

            login_msg = {
                "id": self._next_msg_id(),
                "cmd": "login",
                "params": {
                    "api_key": KALSHI_API_KEY_ID,
                    "signature": sig,
                    "timestamp": timestamp,
                },
            }
            await self._ws.send(json.dumps(login_msg))
            return True, None
        except Exception as e:
            return False, str(e)

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._authenticated = False
        logger.info("Kalshi WS disconnected")

    async def subscribe_market(self, market_tickers: list[str]) -> tuple[bool, str | None]:
        """Subscribe to ticker channel for the given market tickers.

        Returns (success, error) tuple.
        """
        if not self._ws or not self._running:
            return False, "Not connected"

        try:
            self._subscribed_tickers = list(market_tickers)
            sub_msg = {
                "id": self._next_msg_id(),
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker"],
                    "market_tickers": market_tickers,
                },
            }
            await self._ws.send(json.dumps(sub_msg))
            logger.info("Kalshi WS subscribed to %d market tickers", len(market_tickers))
            return True, None
        except Exception as e:
            return False, str(e)

    async def subscribe_fills(self) -> tuple[bool, str | None]:
        """Subscribe to fill notifications (requires authentication).

        Returns (success, error) tuple.
        """
        if not self._ws or not self._running:
            return False, "Not connected"
        if not self._authenticated:
            return False, "Not authenticated — login required for fill channel"

        try:
            sub_msg = {
                "id": self._next_msg_id(),
                "cmd": "subscribe",
                "params": {
                    "channels": ["fill"],
                },
            }
            await self._ws.send(json.dumps(sub_msg))
            logger.info("Kalshi WS subscribed to fill channel")
            return True, None
        except Exception as e:
            return False, str(e)

    async def _listen(self) -> None:
        """Main receive loop — processes incoming messages."""
        try:
            while self._running and self._ws:
                try:
                    raw = await self._ws.recv()
                    self._last_message_time = time.time()
                    await self._handle_message(raw)
                except websockets.ConnectionClosed:
                    if self._running:
                        logger.warning("Kalshi WS connection closed unexpectedly")
                        await self._reconnect()
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Kalshi WS listen error: %s", e)
            if self._running:
                await self._reconnect()

    async def _handle_message(self, raw: str) -> None:
        """Parse a WebSocket message and route to appropriate handler."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Kalshi WS: invalid JSON: %s", raw[:200])
            return

        msg_type = msg.get("type", "")

        if msg_type == "ticker":
            await self._handle_ticker(msg)
        elif msg_type == "fill":
            await self._handle_fill(msg)
        elif msg_type == "error":
            logger.error("Kalshi WS error: %s", msg.get("msg", msg))
        elif msg_type == "subscribed":
            logger.debug("Kalshi WS subscription confirmed: %s", msg.get("channel", ""))
        elif msg_type == "login":
            if msg.get("error"):
                logger.error("Kalshi WS login error: %s", msg.get("error"))
                self._authenticated = False

    async def _handle_ticker(self, msg: dict) -> None:
        """Process a ticker update message and update market state."""
        market_ticker = msg.get("market_ticker", "")
        if not market_ticker:
            return

        # Extract price fields — Kalshi WS sends dollar values as strings
        data = {
            "strike": msg.get("strike", ZERO),
            "yes_bid": msg.get("yes_bid", "0"),
            "yes_ask": msg.get("yes_ask", "0"),
            "no_bid": msg.get("no_bid", "0"),
            "no_ask": msg.get("no_ask", "0"),
            "subtitle": msg.get("subtitle", ""),
        }
        self._market_state.update_market(market_ticker, data)

        if self._on_update:
            markets = self._market_state.get_markets()
            await self._on_update(markets)

    async def _handle_fill(self, msg: dict) -> None:
        """Process a fill notification."""
        if self._on_fill:
            await self._on_fill(msg)

    def get_current_state(self) -> tuple[dict | None, str | None]:
        """Return current market state matching fetch_kalshi_data_struct format.

        Returns (data_dict, error) tuple.
        """
        markets = self._market_state.get_markets()
        if not markets:
            return None, "No Kalshi market data available"

        return {
            "event_ticker": self._subscribed_event_ticker or "",
            "markets": markets,
        }, None

    def set_event_ticker(self, event_ticker: str) -> None:
        """Set the event ticker for state reporting."""
        self._subscribed_event_ticker = event_ticker

    async def _send_heartbeat(self) -> None:
        """Send periodic ping to keep connection alive."""
        try:
            while self._running and self._ws:
                await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
                if self._ws and self._running:
                    try:
                        await self._ws.ping()
                    except Exception:
                        logger.warning("Kalshi WS heartbeat ping failed")
        except asyncio.CancelledError:
            pass

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff, resubscribing to previous channels."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        delay = WS_RECONNECT_BASE_DELAY
        for attempt in range(1, WS_RECONNECT_MAX_RETRIES + 1):
            if not self._running:
                return
            logger.info("Kalshi WS reconnect attempt %d/%d (delay %.1fs)",
                        attempt, WS_RECONNECT_MAX_RETRIES, delay)
            await asyncio.sleep(delay)
            success, err = await self.connect(authenticated=self._authenticated)
            if success:
                # Resubscribe to previously subscribed tickers
                if self._subscribed_tickers:
                    await self.subscribe_market(self._subscribed_tickers)
                if self._authenticated:
                    await self.subscribe_fills()
                logger.info("Kalshi WS reconnected on attempt %d", attempt)
                return
            delay = min(delay * 2, WS_RECONNECT_MAX_DELAY)

        logger.error("Kalshi WS: exhausted %d reconnect attempts", WS_RECONNECT_MAX_RETRIES)
        self._running = False

    @property
    def connected(self) -> bool:
        """Return True if WebSocket is open."""
        return self._ws is not None and self._running

    @property
    def authenticated(self) -> bool:
        """Return True if authenticated for fill notifications."""
        return self._authenticated

    @property
    def last_message_time(self) -> float:
        """Return timestamp of last received message."""
        return self._last_message_time

    @property
    def market_state(self) -> MarketState:
        """Expose the underlying market state for direct access."""
        return self._market_state
