"""Tests for websocket.manager — WebSocketManager."""
import asyncio
import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from websocket.manager import WebSocketManager


@pytest.fixture
def poly_token_ids():
    return {"Up": "token_up", "Down": "token_down"}


@pytest.fixture
def kalshi_tickers():
    return ["KXBTCD-26MAR26-95000", "KXBTCD-26MAR26-96000"]


@pytest.fixture
def poly_strike():
    return Decimal("95500")


class TestWebSocketManagerStart:
    """Tests for starting and stopping the manager."""

    @patch("websocket.manager.KalshiWebSocket")
    @patch("websocket.manager.PolymarketWebSocket")
    async def test_start_both_connected(self, MockPoly, MockKalshi,
                                        poly_token_ids, kalshi_tickers, poly_strike):
        mock_poly = MockPoly.return_value
        mock_poly.connect = AsyncMock(return_value=(True, None))
        mock_poly.disconnect = AsyncMock()
        mock_poly.connected = True

        mock_kalshi = MockKalshi.return_value
        mock_kalshi.connect = AsyncMock(return_value=(True, None))
        mock_kalshi.subscribe_market = AsyncMock(return_value=(True, None))
        mock_kalshi.disconnect = AsyncMock()
        mock_kalshi.connected = True
        mock_kalshi.authenticated = False

        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
        )
        # Replace internal clients with mocks
        manager._poly_ws = mock_poly
        manager._kalshi_ws = mock_kalshi

        success, err = await manager.start()
        assert success is True
        assert err is None

        mock_poly.connect.assert_called_once()
        mock_kalshi.connect.assert_called_once()
        mock_kalshi.subscribe_market.assert_called_once_with(kalshi_tickers)

        await manager.stop()

    @patch("websocket.manager.KalshiWebSocket")
    @patch("websocket.manager.PolymarketWebSocket")
    async def test_start_both_failed(self, MockPoly, MockKalshi,
                                     poly_token_ids, kalshi_tickers, poly_strike):
        mock_poly = MockPoly.return_value
        mock_poly.connect = AsyncMock(return_value=(False, "poly error"))
        mock_poly.disconnect = AsyncMock()

        mock_kalshi = MockKalshi.return_value
        mock_kalshi.connect = AsyncMock(return_value=(False, "kalshi error"))
        mock_kalshi.disconnect = AsyncMock()

        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
        )
        manager._poly_ws = mock_poly
        manager._kalshi_ws = mock_kalshi

        success, err = await manager.start()
        assert success is False
        assert "poly error" in err
        assert "kalshi error" in err

    @patch("websocket.manager.KalshiWebSocket")
    @patch("websocket.manager.PolymarketWebSocket")
    async def test_start_partial_success(self, MockPoly, MockKalshi,
                                         poly_token_ids, kalshi_tickers, poly_strike):
        mock_poly = MockPoly.return_value
        mock_poly.connect = AsyncMock(return_value=(True, None))
        mock_poly.disconnect = AsyncMock()

        mock_kalshi = MockKalshi.return_value
        mock_kalshi.connect = AsyncMock(return_value=(False, "kalshi down"))
        mock_kalshi.disconnect = AsyncMock()

        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
        )
        manager._poly_ws = mock_poly
        manager._kalshi_ws = mock_kalshi

        success, err = await manager.start()
        # Partial success still returns True
        assert success is True

        await manager.stop()


class TestWebSocketManagerScans:
    """Tests for arbitrage scan triggering."""

    async def test_on_poly_update_triggers_scan(self, poly_token_ids, kalshi_tickers, poly_strike):
        opportunity_callback = AsyncMock()
        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
            on_opportunity=opportunity_callback,
        )
        # Pre-load Kalshi data
        manager._kalshi_markets = [
            {"strike": Decimal("95000"), "yes_ask": Decimal("0.50"), "no_ask": Decimal("0.52"),
             "yes_bid": Decimal("0.48"), "no_bid": Decimal("0.46")},
        ]

        # Simulate Polymarket update
        await manager._on_poly_update(
            prices={"Up": Decimal("0.55"), "Down": Decimal("0.45")},
            depth={"Up": Decimal("100"), "Down": Decimal("80")},
        )

        opportunity_callback.assert_called_once()
        checks, opportunities = opportunity_callback.call_args[0]
        assert isinstance(checks, list)
        assert isinstance(opportunities, list)

    async def test_on_kalshi_update_triggers_scan(self, poly_token_ids, kalshi_tickers, poly_strike):
        opportunity_callback = AsyncMock()
        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
            on_opportunity=opportunity_callback,
        )
        # Pre-load Poly data
        manager._poly_prices = {"Up": Decimal("0.55"), "Down": Decimal("0.45")}

        # Simulate Kalshi update
        await manager._on_kalshi_update([
            {"strike": Decimal("96000"), "yes_ask": Decimal("0.40"), "no_ask": Decimal("0.60"),
             "yes_bid": Decimal("0.38"), "no_bid": Decimal("0.58")},
        ])

        opportunity_callback.assert_called_once()

    async def test_scan_skipped_without_both_sides(self, poly_token_ids, kalshi_tickers, poly_strike):
        opportunity_callback = AsyncMock()
        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
            on_opportunity=opportunity_callback,
        )

        # Only Poly data, no Kalshi
        await manager._on_poly_update(
            prices={"Up": Decimal("0.55"), "Down": Decimal("0.45")},
            depth={"Up": Decimal("100"), "Down": Decimal("80")},
        )

        opportunity_callback.assert_not_called()

    async def test_scan_throttle(self, poly_token_ids, kalshi_tickers, poly_strike):
        """Scans within WS_SCAN_INTERVAL should be throttled."""
        opportunity_callback = AsyncMock()
        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
            on_opportunity=opportunity_callback,
        )
        manager._poly_prices = {"Up": Decimal("0.55"), "Down": Decimal("0.45")}
        manager._kalshi_markets = [
            {"strike": Decimal("95000"), "yes_ask": Decimal("0.50"), "no_ask": Decimal("0.52"),
             "yes_bid": Decimal("0.48"), "no_bid": Decimal("0.46")},
        ]

        # First scan should work
        await manager._maybe_run_scan()
        assert opportunity_callback.call_count == 1

        # Immediate second scan should be throttled
        await manager._maybe_run_scan()
        assert opportunity_callback.call_count == 1  # still 1

    @patch("websocket.manager.PRICE_SUM_MIN", Decimal("0.85"))
    @patch("websocket.manager.PRICE_SUM_MAX", Decimal("1.15"))
    async def test_scan_skipped_stale_prices(self, poly_token_ids, kalshi_tickers, poly_strike):
        """Sanity check failure should skip the scan."""
        opportunity_callback = AsyncMock()
        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
            on_opportunity=opportunity_callback,
        )
        # Prices that don't sum to ~1.0
        manager._poly_prices = {"Up": Decimal("0.10"), "Down": Decimal("0.10")}
        manager._kalshi_markets = [
            {"strike": Decimal("95000"), "yes_ask": Decimal("0.50"), "no_ask": Decimal("0.52")},
        ]

        await manager._run_arbitrage_scan()
        opportunity_callback.assert_not_called()


class TestWebSocketManagerStatus:
    """Tests for status reporting."""

    @patch("websocket.manager.KalshiWebSocket")
    @patch("websocket.manager.PolymarketWebSocket")
    async def test_get_status(self, MockPoly, MockKalshi,
                               poly_token_ids, kalshi_tickers, poly_strike):
        mock_poly = MockPoly.return_value
        mock_poly.connected = True
        mock_poly.last_message_time = 1000.0
        mock_poly.disconnect = AsyncMock()

        mock_kalshi = MockKalshi.return_value
        mock_kalshi.connected = True
        mock_kalshi.authenticated = False
        mock_kalshi.last_message_time = 1001.0
        mock_kalshi.disconnect = AsyncMock()

        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
        )
        manager._poly_ws = mock_poly
        manager._kalshi_ws = mock_kalshi

        status = manager.get_status()
        assert status["polymarket_connected"] is True
        assert status["kalshi_connected"] is True
        assert status["kalshi_authenticated"] is False
        assert status["scan_count"] == 0

    async def test_arbitrage_detection_through_manager(self, poly_token_ids, kalshi_tickers):
        """Integration test: verify run_arbitrage_checks finds opportunity through manager."""
        opportunity_callback = AsyncMock()
        # Poly strike higher than Kalshi strike → buy Poly Down + Kalshi Yes
        poly_strike = Decimal("96000")
        manager = WebSocketManager(
            poly_token_ids=poly_token_ids,
            kalshi_market_tickers=kalshi_tickers,
            poly_strike=poly_strike,
            on_opportunity=opportunity_callback,
        )

        # Set up prices that create an arbitrage opportunity
        # Poly Down = 0.30, Kalshi Yes = 0.40 → total 0.70 < 1.00
        manager._poly_prices = {"Up": Decimal("0.70"), "Down": Decimal("0.30")}
        manager._kalshi_markets = [
            {"strike": Decimal("95000"), "yes_ask": Decimal("0.40"), "no_ask": Decimal("0.60"),
             "yes_bid": Decimal("0.38"), "no_bid": Decimal("0.58")},
        ]

        await manager._run_arbitrage_scan()

        opportunity_callback.assert_called_once()
        checks, opportunities = opportunity_callback.call_args[0]
        assert len(opportunities) > 0
        opp = opportunities[0]
        assert opp["is_arbitrage"] is True
        assert opp["total_cost"] < Decimal("1")
        assert opp["margin"] > Decimal("0")
