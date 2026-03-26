"""Polymarket WebSocket client for real-time order book updates.

Connects to the Polymarket CLOB WebSocket and maintains local order book
state for Up/Down tokens. Fires a callback when prices change.
"""
import asyncio
import json
import logging
import time
from decimal import Decimal

import websockets

from config import (
    WS_POLYMARKET_URL,
    WS_RECONNECT_BASE_DELAY,
    WS_RECONNECT_MAX_DELAY,
    WS_RECONNECT_MAX_RETRIES,
    WS_HEARTBEAT_INTERVAL,
)
from websocket.order_book import OrderBook, ZERO

logger = logging.getLogger(__name__)


class PolymarketWebSocket:
    """Real-time order book client for Polymarket CLOB.

    Subscribes to order book channels for given token IDs and maintains
    local OrderBook instances. Calls on_update callback when prices change.

    Args:
        token_ids: Dict mapping outcome name to token ID, e.g. {"Up": "abc", "Down": "def"}.
        on_update: Async callback(prices, depth) fired on each book update.
    """

    def __init__(self, token_ids: dict[str, str], on_update=None):
        self._token_ids = token_ids  # {"Up": "token_abc", "Down": "token_def"}
        self._on_update = on_update
        self._books: dict[str, OrderBook] = {}  # token_id -> OrderBook
        self._token_to_outcome: dict[str, str] = {}  # token_id -> "Up"/"Down"
        for outcome, token_id in token_ids.items():
            self._books[token_id] = OrderBook()
            self._token_to_outcome[token_id] = outcome
        self._ws = None
        self._running = False
        self._listen_task = None
        self._heartbeat_task = None
        self._last_message_time = 0.0

    async def connect(self) -> tuple[bool, str | None]:
        """Connect to Polymarket WebSocket and subscribe to book channels.

        Returns (success, error) tuple.
        """
        try:
            self._ws = await websockets.connect(WS_POLYMARKET_URL)
            self._running = True
            self._last_message_time = time.time()

            # Subscribe to book channel for all token IDs
            asset_ids = list(self._token_ids.values())
            subscribe_msg = {
                "type": "subscribe",
                "channel": "book",
                "assets_ids": asset_ids,
            }
            await self._ws.send(json.dumps(subscribe_msg))
            logger.info("Polymarket WS connected, subscribed to %d tokens", len(asset_ids))

            # Start background tasks
            self._listen_task = asyncio.ensure_future(self._listen())
            self._heartbeat_task = asyncio.ensure_future(self._send_heartbeat())

            return True, None
        except Exception as e:
            logger.error("Polymarket WS connect failed: %s", e)
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
        logger.info("Polymarket WS disconnected")

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
                        logger.warning("Polymarket WS connection closed unexpectedly")
                        await self._reconnect()
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Polymarket WS listen error: %s", e)
            if self._running:
                await self._reconnect()

    async def _handle_message(self, raw: str) -> None:
        """Parse a WebSocket message and update local order book state."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Polymarket WS: invalid JSON: %s", raw[:200])
            return

        msg_type = msg.get("type", "")
        asset_id = msg.get("asset_id", "")

        if msg_type == "book" and asset_id in self._books:
            # Full snapshot
            book = self._books[asset_id]
            asks = msg.get("asks", [])
            bids = msg.get("bids", [])
            book.apply_snapshot(
                [[a["price"], a["size"]] for a in asks],
                [[b["price"], b["size"]] for b in bids],
            )
            await self._fire_update()

        elif msg_type == "book_delta" and asset_id in self._books:
            # Incremental update
            book = self._books[asset_id]
            asks = msg.get("asks", [])
            bids = msg.get("bids", [])
            book.apply_delta(
                [[a["price"], a["size"]] for a in asks] if asks else None,
                [[b["price"], b["size"]] for b in bids] if bids else None,
            )
            await self._fire_update()

        elif msg_type == "error":
            logger.error("Polymarket WS error message: %s", msg.get("message", ""))

    async def _fire_update(self) -> None:
        """Build current state and invoke callback."""
        if self._on_update:
            prices, depth = self._get_prices_and_depth()
            await self._on_update(prices, depth)

    def _get_prices_and_depth(self) -> tuple[dict, dict]:
        """Extract current best-ask prices and depth from local books."""
        prices = {}
        depth = {}
        for token_id, book in self._books.items():
            outcome = self._token_to_outcome[token_id]
            price, size = book.get_best_ask()
            prices[outcome] = price
            depth[outcome] = size
        return prices, depth

    def get_current_state(self) -> tuple[dict | None, str | None]:
        """Return current prices in the same format as fetch_polymarket_data_struct.

        Returns (data_dict, error) tuple.
        """
        prices, depth = self._get_prices_and_depth()

        # Check that we have data for all outcomes
        for outcome in self._token_ids:
            if outcome not in prices:
                return None, f"No data for {outcome} token"

        return {"prices": prices, "depth": depth}, None

    async def _send_heartbeat(self) -> None:
        """Send periodic ping to keep connection alive."""
        try:
            while self._running and self._ws:
                await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
                if self._ws and self._running:
                    try:
                        await self._ws.ping()
                    except Exception:
                        logger.warning("Polymarket WS heartbeat ping failed")
        except asyncio.CancelledError:
            pass

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
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
            logger.info("Polymarket WS reconnect attempt %d/%d (delay %.1fs)",
                        attempt, WS_RECONNECT_MAX_RETRIES, delay)
            await asyncio.sleep(delay)
            success, err = await self.connect()
            if success:
                logger.info("Polymarket WS reconnected on attempt %d", attempt)
                return
            delay = min(delay * 2, WS_RECONNECT_MAX_DELAY)

        logger.error("Polymarket WS: exhausted %d reconnect attempts", WS_RECONNECT_MAX_RETRIES)
        self._running = False

    @property
    def connected(self) -> bool:
        """Return True if WebSocket is open."""
        return self._ws is not None and self._running

    @property
    def last_message_time(self) -> float:
        """Return timestamp of last received message."""
        return self._last_message_time
