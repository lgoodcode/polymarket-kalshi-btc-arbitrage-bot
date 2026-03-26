"""Tests for websocket.polymarket_ws — PolymarketWebSocket client."""
import asyncio
import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from websocket.polymarket_ws import PolymarketWebSocket
from websocket.order_book import ZERO


@pytest.fixture
def token_ids():
    return {"Up": "token_up_123", "Down": "token_down_456"}


@pytest.fixture
def mock_ws():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.close = AsyncMock()
    ws.send = AsyncMock()
    ws.ping = AsyncMock()
    ws.recv = AsyncMock(side_effect=asyncio.CancelledError)
    return ws


def _patch_ws_connect():
    """Patch websockets.connect as an AsyncMock so `await` works."""
    return patch("websocket.polymarket_ws.websockets.connect", new_callable=AsyncMock)


class TestPolymarketWebSocketConnect:
    """Tests for connection and subscription."""

    async def test_connect_success(self, token_ids, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = PolymarketWebSocket(token_ids)
            success, err = await client.connect()

            assert success is True
            assert err is None
            assert client.connected

            # Verify subscription message
            mock_ws.send.assert_called_once()
            sub_msg = json.loads(mock_ws.send.call_args[0][0])
            assert sub_msg["type"] == "subscribe"
            assert sub_msg["channel"] == "book"
            assert set(sub_msg["assets_ids"]) == {"token_up_123", "token_down_456"}

            await client.disconnect()

    async def test_connect_failure(self, token_ids):
        with _patch_ws_connect() as mock_connect:
            mock_connect.side_effect = ConnectionRefusedError("refused")

            client = PolymarketWebSocket(token_ids)
            success, err = await client.connect()

            assert success is False
            assert "refused" in err
            assert not client.connected

    async def test_disconnect(self, token_ids, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = PolymarketWebSocket(token_ids)
            await client.connect()
            await client.disconnect()

            assert not client.connected
            mock_ws.close.assert_called_once()


class TestPolymarketWebSocketMessages:
    """Tests for message handling."""

    async def test_handle_book_snapshot(self, token_ids):
        """Test that a book snapshot updates the order book."""
        update_callback = AsyncMock()
        client = PolymarketWebSocket(token_ids, on_update=update_callback)

        snapshot_msg = json.dumps({
            "type": "book",
            "asset_id": "token_up_123",
            "asks": [{"price": "0.55", "size": "100"}, {"price": "0.60", "size": "50"}],
            "bids": [{"price": "0.50", "size": "200"}],
        })
        await client._handle_message(snapshot_msg)

        update_callback.assert_called_once()
        prices, depth = update_callback.call_args[0]
        assert prices["Up"] == Decimal("0.55")
        assert depth["Up"] == Decimal("100")

    async def test_handle_book_delta(self, token_ids):
        """Test incremental delta updates."""
        update_callback = AsyncMock()
        client = PolymarketWebSocket(token_ids, on_update=update_callback)

        # First apply snapshot
        await client._handle_message(json.dumps({
            "type": "book",
            "asset_id": "token_up_123",
            "asks": [{"price": "0.55", "size": "100"}],
            "bids": [],
        }))

        # Then apply delta
        await client._handle_message(json.dumps({
            "type": "book_delta",
            "asset_id": "token_up_123",
            "asks": [{"price": "0.55", "size": "75"}],
            "bids": [],
        }))

        assert update_callback.call_count == 2
        prices, depth = update_callback.call_args[0]
        assert prices["Up"] == Decimal("0.55")
        assert depth["Up"] == Decimal("75")

    async def test_handle_unknown_asset_id(self, token_ids):
        """Messages for unknown asset IDs should be ignored."""
        update_callback = AsyncMock()
        client = PolymarketWebSocket(token_ids, on_update=update_callback)

        await client._handle_message(json.dumps({
            "type": "book",
            "asset_id": "unknown_token",
            "asks": [{"price": "0.55", "size": "100"}],
            "bids": [],
        }))

        update_callback.assert_not_called()

    async def test_handle_invalid_json(self, token_ids):
        """Invalid JSON should be logged and not crash."""
        client = PolymarketWebSocket(token_ids)
        await client._handle_message("not valid json {{{")

    async def test_handle_error_message(self, token_ids):
        """Error messages should be logged."""
        client = PolymarketWebSocket(token_ids)
        await client._handle_message(json.dumps({
            "type": "error",
            "message": "subscription failed",
        }))


class TestPolymarketWebSocketState:
    """Tests for get_current_state."""

    def test_get_current_state_no_data(self, token_ids):
        client = PolymarketWebSocket(token_ids)
        state, err = client.get_current_state()
        assert state is not None
        assert state["prices"]["Up"] == ZERO
        assert state["prices"]["Down"] == ZERO

    async def test_get_current_state_with_data(self, token_ids):
        client = PolymarketWebSocket(token_ids)

        await client._handle_message(json.dumps({
            "type": "book",
            "asset_id": "token_up_123",
            "asks": [{"price": "0.55", "size": "100"}],
            "bids": [],
        }))
        await client._handle_message(json.dumps({
            "type": "book",
            "asset_id": "token_down_456",
            "asks": [{"price": "0.45", "size": "80"}],
            "bids": [],
        }))

        state, err = client.get_current_state()
        assert err is None
        assert state["prices"]["Up"] == Decimal("0.55")
        assert state["prices"]["Down"] == Decimal("0.45")
        assert state["depth"]["Up"] == Decimal("100")
        assert state["depth"]["Down"] == Decimal("80")


class TestPolymarketWebSocketReconnect:
    """Tests for reconnection logic."""

    @patch("websocket.polymarket_ws.WS_RECONNECT_BASE_DELAY", 0.01)
    @patch("websocket.polymarket_ws.WS_RECONNECT_MAX_RETRIES", 2)
    async def test_reconnect_success(self, token_ids, mock_ws):
        """Test successful reconnection after failure."""
        with _patch_ws_connect() as mock_connect:
            mock_connect.side_effect = [
                ConnectionRefusedError("fail"),
                mock_ws,
            ]

            client = PolymarketWebSocket(token_ids)
            client._running = True
            await client._reconnect()

            assert client.connected
            await client.disconnect()

    @patch("websocket.polymarket_ws.WS_RECONNECT_BASE_DELAY", 0.01)
    @patch("websocket.polymarket_ws.WS_RECONNECT_MAX_RETRIES", 2)
    async def test_reconnect_exhausted(self, token_ids):
        """Test that exhausted retries stops the client."""
        with _patch_ws_connect() as mock_connect:
            mock_connect.side_effect = ConnectionRefusedError("fail")

            client = PolymarketWebSocket(token_ids)
            client._running = True
            await client._reconnect()

            assert not client._running


class TestPolymarketWebSocketHeartbeat:
    """Tests for heartbeat/keepalive."""

    @patch("websocket.polymarket_ws.WS_HEARTBEAT_INTERVAL", 0.05)
    async def test_heartbeat_sends_ping(self, token_ids, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = PolymarketWebSocket(token_ids)
            await client.connect()

            # Wait for at least one heartbeat
            await asyncio.sleep(0.15)

            assert mock_ws.ping.called

            await client.disconnect()
