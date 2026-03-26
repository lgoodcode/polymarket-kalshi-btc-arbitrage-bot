"""Tests for websocket.kalshi_ws — KalshiWebSocket client."""
import asyncio
import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from websocket.kalshi_ws import KalshiWebSocket
from websocket.order_book import ZERO


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
    return patch("websocket.kalshi_ws.websockets.connect", new_callable=AsyncMock)


class TestKalshiWebSocketConnect:
    """Tests for connection and subscription."""

    async def test_connect_success(self, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = KalshiWebSocket()
            success, err = await client.connect()

            assert success is True
            assert err is None
            assert client.connected
            assert not client.authenticated

            await client.disconnect()

    async def test_connect_failure(self):
        with _patch_ws_connect() as mock_connect:
            mock_connect.side_effect = ConnectionRefusedError("refused")

            client = KalshiWebSocket()
            success, err = await client.connect()

            assert success is False
            assert "refused" in err

    async def test_disconnect(self, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = KalshiWebSocket()
            await client.connect()
            await client.disconnect()

            assert not client.connected
            mock_ws.close.assert_called_once()

    async def test_connect_with_auth_no_credentials(self, mock_ws):
        """Auth with no credentials should log warning and continue unauthenticated."""
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = KalshiWebSocket()
            success, err = await client.connect(authenticated=True)

            assert success is True
            assert not client.authenticated

            await client.disconnect()


class TestKalshiWebSocketSubscribe:
    """Tests for market and fill subscriptions."""

    async def test_subscribe_market(self, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = KalshiWebSocket()
            await client.connect()

            tickers = ["KXBTCD-26MAR26-95000", "KXBTCD-26MAR26-96000"]
            success, err = await client.subscribe_market(tickers)

            assert success is True
            assert err is None

            # Verify subscription message format
            sub_msg = json.loads(mock_ws.send.call_args[0][0])
            assert sub_msg["cmd"] == "subscribe"
            assert "ticker" in sub_msg["params"]["channels"]
            assert sub_msg["params"]["market_tickers"] == tickers

            await client.disconnect()

    async def test_subscribe_market_not_connected(self):
        client = KalshiWebSocket()
        success, err = await client.subscribe_market(["TICKER"])

        assert success is False
        assert "Not connected" in err

    async def test_subscribe_fills_not_authenticated(self, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = KalshiWebSocket()
            await client.connect()

            success, err = await client.subscribe_fills()
            assert success is False
            assert "Not authenticated" in err

            await client.disconnect()


class TestKalshiWebSocketMessages:
    """Tests for message handling."""

    async def test_handle_ticker_update(self):
        update_callback = AsyncMock()
        client = KalshiWebSocket(on_update=update_callback)

        await client._handle_message(json.dumps({
            "type": "ticker",
            "market_ticker": "KXBTCD-26MAR26-95000",
            "strike": "95000",
            "yes_bid": "0.45",
            "yes_ask": "0.50",
            "no_bid": "0.48",
            "no_ask": "0.52",
            "subtitle": "$95,000 or above",
        }))

        update_callback.assert_called_once()
        markets = update_callback.call_args[0][0]
        assert len(markets) == 1
        assert markets[0]["strike"] == Decimal("95000")
        assert markets[0]["yes_ask"] == Decimal("0.50")

    async def test_handle_multiple_tickers(self):
        update_callback = AsyncMock()
        client = KalshiWebSocket(on_update=update_callback)

        await client._handle_message(json.dumps({
            "type": "ticker",
            "market_ticker": "MKT-HIGH",
            "strike": "97000",
            "yes_ask": "0.30",
            "no_ask": "0.70",
        }))
        await client._handle_message(json.dumps({
            "type": "ticker",
            "market_ticker": "MKT-LOW",
            "strike": "93000",
            "yes_ask": "0.70",
            "no_ask": "0.30",
        }))

        assert update_callback.call_count == 2
        markets = update_callback.call_args[0][0]
        assert len(markets) == 2
        assert markets[0]["strike"] == Decimal("93000")
        assert markets[1]["strike"] == Decimal("97000")

    async def test_handle_fill_notification(self):
        fill_callback = AsyncMock()
        client = KalshiWebSocket(on_fill=fill_callback)

        fill_msg = {
            "type": "fill",
            "order_id": "order-123",
            "ticker": "KXBTCD-26MAR26-95000",
            "side": "yes",
            "count": 10,
            "price": "0.50",
        }
        await client._handle_message(json.dumps(fill_msg))

        fill_callback.assert_called_once()
        received = fill_callback.call_args[0][0]
        assert received["order_id"] == "order-123"

    async def test_handle_invalid_json(self):
        client = KalshiWebSocket()
        await client._handle_message("not json {{{")

    async def test_handle_error_message(self):
        client = KalshiWebSocket()
        await client._handle_message(json.dumps({
            "type": "error",
            "msg": "invalid subscription",
        }))

    async def test_handle_ticker_no_market_ticker(self):
        """Ticker message without market_ticker field should be ignored."""
        update_callback = AsyncMock()
        client = KalshiWebSocket(on_update=update_callback)

        await client._handle_message(json.dumps({
            "type": "ticker",
            "strike": "95000",
            "yes_ask": "0.50",
        }))

        update_callback.assert_not_called()


class TestKalshiWebSocketState:
    """Tests for get_current_state."""

    def test_get_current_state_no_data(self):
        client = KalshiWebSocket()
        state, err = client.get_current_state()
        assert state is None
        assert "No Kalshi market data" in err

    async def test_get_current_state_with_data(self):
        client = KalshiWebSocket()
        client.set_event_ticker("KXBTCD-26MAR2614")

        await client._handle_message(json.dumps({
            "type": "ticker",
            "market_ticker": "KXBTCD-26MAR26-95000",
            "strike": "95000",
            "yes_ask": "0.50",
            "no_ask": "0.52",
        }))

        state, err = client.get_current_state()
        assert err is None
        assert state["event_ticker"] == "KXBTCD-26MAR2614"
        assert len(state["markets"]) == 1
        assert state["markets"][0]["yes_ask"] == Decimal("0.50")

    def test_set_event_ticker(self):
        client = KalshiWebSocket()
        client.set_event_ticker("KXBTCD-26MAR2614")
        assert client._subscribed_event_ticker == "KXBTCD-26MAR2614"


class TestKalshiWebSocketReconnect:
    """Tests for reconnection logic."""

    @patch("websocket.kalshi_ws.WS_RECONNECT_BASE_DELAY", 0.01)
    @patch("websocket.kalshi_ws.WS_RECONNECT_MAX_RETRIES", 2)
    async def test_reconnect_success(self, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.side_effect = [
                ConnectionRefusedError("fail"),
                mock_ws,
            ]

            client = KalshiWebSocket()
            client._running = True
            client._subscribed_tickers = ["TICKER-1"]
            await client._reconnect()

            assert client.connected
            # Should resubscribe
            sub_calls = [
                call for call in mock_ws.send.call_args_list
                if "subscribe" in call[0][0]
            ]
            assert len(sub_calls) >= 1

            await client.disconnect()

    @patch("websocket.kalshi_ws.WS_RECONNECT_BASE_DELAY", 0.01)
    @patch("websocket.kalshi_ws.WS_RECONNECT_MAX_RETRIES", 2)
    async def test_reconnect_exhausted(self):
        with _patch_ws_connect() as mock_connect:
            mock_connect.side_effect = ConnectionRefusedError("fail")

            client = KalshiWebSocket()
            client._running = True
            await client._reconnect()

            assert not client._running


class TestKalshiWebSocketHeartbeat:
    """Tests for heartbeat/keepalive."""

    @patch("websocket.kalshi_ws.WS_HEARTBEAT_INTERVAL", 0.05)
    async def test_heartbeat_sends_ping(self, mock_ws):
        with _patch_ws_connect() as mock_connect:
            mock_connect.return_value = mock_ws

            client = KalshiWebSocket()
            await client.connect()

            await asyncio.sleep(0.15)
            assert mock_ws.ping.called

            await client.disconnect()
