"""Tests for ws_bot — WebSocket bot entry point."""
import asyncio
import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from ws_bot import (
    resolve_poly_token_ids,
    resolve_kalshi_tickers,
    format_opportunity,
    on_opportunity,
)


class TestResolvePolyTokenIds:
    """Tests for resolving Polymarket token IDs."""

    async def test_resolve_success(self):
        session = AsyncMock()
        mock_response = [{
            "markets": [{
                "clobTokenIds": json.dumps(["token_up_123", "token_down_456"]),
                "outcomes": json.dumps(["Up", "Down"]),
            }],
        }]

        with patch("ws_bot.fetch_json", AsyncMock(return_value=mock_response)):
            tokens, err = await resolve_poly_token_ids(session, "test-slug")

        assert err is None
        assert tokens == {"Up": "token_up_123", "Down": "token_down_456"}

    async def test_resolve_empty_event(self):
        session = AsyncMock()

        with patch("ws_bot.fetch_json", AsyncMock(return_value=[])):
            tokens, err = await resolve_poly_token_ids(session, "test-slug")

        assert tokens is None
        assert "Event not found" in err

    async def test_resolve_no_markets(self):
        session = AsyncMock()
        mock_response = [{"markets": []}]

        with patch("ws_bot.fetch_json", AsyncMock(return_value=mock_response)):
            tokens, err = await resolve_poly_token_ids(session, "test-slug")

        assert tokens is None
        assert "No markets" in err

    async def test_resolve_wrong_token_count(self):
        session = AsyncMock()
        mock_response = [{
            "markets": [{
                "clobTokenIds": json.dumps(["token_only_one"]),
                "outcomes": json.dumps(["Up"]),
            }],
        }]

        with patch("ws_bot.fetch_json", AsyncMock(return_value=mock_response)):
            tokens, err = await resolve_poly_token_ids(session, "test-slug")

        assert tokens is None
        assert "Unexpected" in err

    async def test_resolve_exception(self):
        session = AsyncMock()

        with patch("ws_bot.fetch_json", AsyncMock(side_effect=Exception("network error"))):
            tokens, err = await resolve_poly_token_ids(session, "test-slug")

        assert tokens is None
        assert "network error" in err


class TestResolveKalshiTickers:
    """Tests for resolving Kalshi market tickers."""

    async def test_resolve_success(self):
        session = AsyncMock()
        mock_markets = [
            {"ticker": "KXBTCD-26MAR26-95000"},
            {"ticker": "KXBTCD-26MAR26-96000"},
        ]

        with patch("ws_bot.get_kalshi_markets", AsyncMock(return_value=(mock_markets, None))):
            tickers, err = await resolve_kalshi_tickers(session, "KXBTCD-26MAR2614")

        assert err is None
        assert tickers == ["KXBTCD-26MAR26-95000", "KXBTCD-26MAR26-96000"]

    async def test_resolve_error(self):
        session = AsyncMock()

        with patch("ws_bot.get_kalshi_markets", AsyncMock(return_value=(None, "API error"))):
            tickers, err = await resolve_kalshi_tickers(session, "KXBTCD-26MAR2614")

        assert tickers is None
        assert "API error" in err

    async def test_resolve_empty_markets(self):
        session = AsyncMock()

        with patch("ws_bot.get_kalshi_markets", AsyncMock(return_value=([], None))):
            tickers, err = await resolve_kalshi_tickers(session, "KXBTCD-26MAR2614")

        assert err is None
        assert tickers == []


class TestFormatOpportunity:
    """Tests for opportunity formatting."""

    def test_format_basic(self):
        check = {
            "type": "Poly > Kalshi",
            "kalshi_strike": Decimal("95000"),
            "poly_leg": "Down",
            "kalshi_leg": "Yes",
            "total_cost": Decimal("0.850"),
            "margin": Decimal("0.150"),
        }
        output = format_opportunity(check)
        assert "ARBITRAGE FOUND" in output
        assert "Poly > Kalshi" in output
        assert "Buy Poly Down + Kalshi Yes" in output
        assert "$0.850" in output

    def test_format_with_fees(self):
        check = {
            "type": "Poly < Kalshi",
            "kalshi_strike": Decimal("96000"),
            "poly_leg": "Up",
            "kalshi_leg": "No",
            "total_cost": Decimal("0.900"),
            "margin": Decimal("0.100"),
            "estimated_fees": Decimal("0.0150"),
            "margin_after_fees": Decimal("0.0850"),
            "profitable_after_fees": True,
        }
        output = format_opportunity(check)
        assert "PROFITABLE" in output
        assert "$0.0150" in output


class TestOnOpportunity:
    """Tests for the on_opportunity callback."""

    async def test_prints_opportunities(self, capsys):
        opportunities = [{
            "type": "Poly > Kalshi",
            "kalshi_strike": Decimal("95000"),
            "poly_leg": "Down",
            "kalshi_leg": "Yes",
            "total_cost": Decimal("0.850"),
            "margin": Decimal("0.150"),
        }]
        await on_opportunity([], opportunities)
        captured = capsys.readouterr()
        assert "ARBITRAGE FOUND" in captured.out

    async def test_no_opportunities_no_output(self, capsys):
        await on_opportunity([{"some": "check"}], [])
        captured = capsys.readouterr()
        # Should not print anything for zero opportunities
        assert "ARBITRAGE" not in captured.out
