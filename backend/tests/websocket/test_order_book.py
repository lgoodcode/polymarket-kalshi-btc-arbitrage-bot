"""Tests for websocket.order_book — OrderBook and MarketState."""
import pytest
from decimal import Decimal

from websocket.order_book import OrderBook, MarketState, ZERO


class TestOrderBook:
    """Tests for the OrderBook class."""

    def test_empty_book(self):
        book = OrderBook()
        assert book.is_empty()
        assert book.get_best_ask() == (ZERO, ZERO)
        assert book.get_best_bid() == (ZERO, ZERO)
        assert book.get_depth_at_best_ask() == ZERO

    def test_apply_snapshot(self):
        book = OrderBook()
        book.apply_snapshot(
            asks=[["0.55", "100"], ["0.60", "50"]],
            bids=[["0.50", "200"], ["0.45", "150"]],
        )
        assert not book.is_empty()
        assert book.get_best_ask() == (Decimal("0.55"), Decimal("100"))
        assert book.get_best_bid() == (Decimal("0.50"), Decimal("200"))

    def test_snapshot_replaces_existing(self):
        book = OrderBook()
        book.apply_snapshot(
            asks=[["0.55", "100"]],
            bids=[["0.50", "200"]],
        )
        # Apply new snapshot — old data should be gone
        book.apply_snapshot(
            asks=[["0.70", "30"]],
            bids=[["0.65", "40"]],
        )
        assert book.get_best_ask() == (Decimal("0.70"), Decimal("30"))
        assert book.get_best_bid() == (Decimal("0.65"), Decimal("40"))

    def test_snapshot_skips_zero_size(self):
        book = OrderBook()
        book.apply_snapshot(
            asks=[["0.55", "0"], ["0.60", "50"]],
            bids=[["0.50", "0"]],
        )
        assert book.get_best_ask() == (Decimal("0.60"), Decimal("50"))
        assert book.get_best_bid() == (ZERO, ZERO)

    def test_apply_delta_adds_levels(self):
        book = OrderBook()
        book.apply_snapshot(asks=[["0.55", "100"]], bids=[])
        book.apply_delta(asks=[["0.60", "50"]])
        # Best ask still 0.55
        assert book.get_best_ask() == (Decimal("0.55"), Decimal("100"))

    def test_apply_delta_updates_level(self):
        book = OrderBook()
        book.apply_snapshot(asks=[["0.55", "100"]], bids=[])
        book.apply_delta(asks=[["0.55", "75"]])
        assert book.get_best_ask() == (Decimal("0.55"), Decimal("75"))

    def test_apply_delta_removes_level(self):
        book = OrderBook()
        book.apply_snapshot(
            asks=[["0.55", "100"], ["0.60", "50"]],
            bids=[],
        )
        # Remove best ask (size=0)
        book.apply_delta(asks=[["0.55", "0"]])
        assert book.get_best_ask() == (Decimal("0.60"), Decimal("50"))

    def test_apply_delta_bids(self):
        book = OrderBook()
        book.apply_snapshot(asks=[], bids=[["0.50", "200"]])
        book.apply_delta(bids=[["0.52", "100"]])
        assert book.get_best_bid() == (Decimal("0.52"), Decimal("100"))

    def test_apply_delta_none_sides(self):
        book = OrderBook()
        book.apply_snapshot(asks=[["0.55", "100"]], bids=[["0.50", "200"]])
        # Delta with None sides should not crash
        book.apply_delta(asks=None, bids=None)
        assert book.get_best_ask() == (Decimal("0.55"), Decimal("100"))
        assert book.get_best_bid() == (Decimal("0.50"), Decimal("200"))

    def test_get_depth_at_best_ask(self):
        book = OrderBook()
        book.apply_snapshot(asks=[["0.55", "123"]], bids=[])
        assert book.get_depth_at_best_ask() == Decimal("123")

    def test_clear(self):
        book = OrderBook()
        book.apply_snapshot(asks=[["0.55", "100"]], bids=[["0.50", "200"]])
        book.clear()
        assert book.is_empty()

    def test_multiple_ask_levels_best_is_lowest(self):
        book = OrderBook()
        book.apply_snapshot(
            asks=[["0.70", "10"], ["0.55", "100"], ["0.60", "50"]],
            bids=[],
        )
        assert book.get_best_ask() == (Decimal("0.55"), Decimal("100"))

    def test_multiple_bid_levels_best_is_highest(self):
        book = OrderBook()
        book.apply_snapshot(
            asks=[],
            bids=[["0.40", "10"], ["0.50", "100"], ["0.45", "50"]],
        )
        assert book.get_best_bid() == (Decimal("0.50"), Decimal("100"))

    def test_numeric_inputs(self):
        """Test that numeric (non-string) inputs are handled."""
        book = OrderBook()
        book.apply_snapshot(
            asks=[[0.55, 100], [0.60, 50]],
            bids=[[0.50, 200]],
        )
        assert book.get_best_ask() == (Decimal("0.55"), Decimal("100"))


class TestMarketState:
    """Tests for the MarketState class."""

    def test_empty_state(self):
        state = MarketState()
        assert len(state) == 0
        assert state.get_markets() == []

    def test_update_and_get_market(self):
        state = MarketState()
        state.update_market("MKT-1", {
            "strike": "95000",
            "yes_bid": "0.45",
            "yes_ask": "0.50",
            "no_bid": "0.48",
            "no_ask": "0.52",
            "subtitle": "$95,000 or above",
        })
        assert len(state) == 1
        market = state.get_market("MKT-1")
        assert market is not None
        assert market["strike"] == Decimal("95000")
        assert market["yes_ask"] == Decimal("0.50")
        assert market["subtitle"] == "$95,000 or above"

    def test_get_markets_sorted_by_strike(self):
        state = MarketState()
        state.update_market("MKT-HIGH", {
            "strike": "97000", "yes_ask": "0.30", "no_ask": "0.70",
        })
        state.update_market("MKT-LOW", {
            "strike": "93000", "yes_ask": "0.70", "no_ask": "0.30",
        })
        state.update_market("MKT-MID", {
            "strike": "95000", "yes_ask": "0.50", "no_ask": "0.50",
        })
        markets = state.get_markets()
        assert len(markets) == 3
        assert markets[0]["strike"] == Decimal("93000")
        assert markets[1]["strike"] == Decimal("95000")
        assert markets[2]["strike"] == Decimal("97000")

    def test_update_overwrites_existing(self):
        state = MarketState()
        state.update_market("MKT-1", {"strike": "95000", "yes_ask": "0.50", "no_ask": "0.50"})
        state.update_market("MKT-1", {"strike": "95000", "yes_ask": "0.55", "no_ask": "0.45"})
        assert len(state) == 1
        market = state.get_market("MKT-1")
        assert market["yes_ask"] == Decimal("0.55")

    def test_remove_market(self):
        state = MarketState()
        state.update_market("MKT-1", {"strike": "95000", "yes_ask": "0.50", "no_ask": "0.50"})
        state.remove_market("MKT-1")
        assert len(state) == 0
        assert state.get_market("MKT-1") is None

    def test_remove_nonexistent(self):
        state = MarketState()
        # Should not raise
        state.remove_market("DOES-NOT-EXIST")

    def test_clear(self):
        state = MarketState()
        state.update_market("MKT-1", {"strike": "95000", "yes_ask": "0.50", "no_ask": "0.50"})
        state.update_market("MKT-2", {"strike": "96000", "yes_ask": "0.40", "no_ask": "0.60"})
        state.clear()
        assert len(state) == 0

    def test_default_values(self):
        """Missing fields should default to zero/empty."""
        state = MarketState()
        state.update_market("MKT-1", {"strike": "95000"})
        market = state.get_market("MKT-1")
        assert market["yes_bid"] == Decimal("0")
        assert market["yes_ask"] == Decimal("0")
        assert market["no_bid"] == Decimal("0")
        assert market["no_ask"] == Decimal("0")
        assert market["subtitle"] == ""

    def test_format_matches_kalshi_data_struct(self):
        """Verify output format is compatible with run_arbitrage_checks."""
        state = MarketState()
        state.update_market("MKT-1", {
            "strike": "95000",
            "yes_bid": "0.45",
            "yes_ask": "0.50",
            "no_bid": "0.48",
            "no_ask": "0.52",
            "subtitle": "$95,000 or above",
        })
        markets = state.get_markets()
        m = markets[0]
        # These are the fields run_arbitrage_checks expects
        assert "strike" in m
        assert "yes_ask" in m
        assert "no_ask" in m
        assert isinstance(m["strike"], Decimal)
        assert isinstance(m["yes_ask"], Decimal)
        assert isinstance(m["no_ask"], Decimal)
