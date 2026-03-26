import datetime
import pytz
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from arbitrage_bot import _estimate_fees, check_arbitrage

UTC = pytz.utc


# --- _estimate_fees tests ---

class TestEstimateFees:
    def test_both_half(self):
        result = _estimate_fees(0.50, 0.50)
        assert result == Decimal("0.0356")

    def test_both_zero(self):
        result = _estimate_fees(0.0, 0.0)
        assert result == Decimal("0.0000")

    def test_both_one(self):
        result = _estimate_fees(1.0, 1.0)
        assert result == Decimal("0.0000")

    def test_one_at_one(self):
        result = _estimate_fees(1.0, 0.50)
        assert result == Decimal("0.0200")


# --- check_arbitrage tests ---

@patch('arbitrage_bot.get_binance_current_price', new_callable=AsyncMock, return_value=(Decimal("95500"), None))
class TestCheckArbitrage:
    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_poly_error(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (None, "Polymarket Error: API down")
        mock_kalshi.return_value = (None, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "Polymarket Error" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_kalshi_error(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({"price_to_beat": Decimal("95000"), "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.47")}, "depth": {"Up": Decimal("100"), "Down": Decimal("200")}}, None)
        mock_kalshi.return_value = (None, "Kalshi Error: API down")

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "Kalshi Error" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_missing_data(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = (None, None)
        mock_kalshi.return_value = (None, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "Missing data" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_poly_strike_none(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": None,
            "current_price": Decimal("95500"),
            "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.47")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("95500"),
            "markets": [{"strike": Decimal("95000"), "yes_bid": Decimal("0.50"), "yes_ask": Decimal("0.52"), "no_bid": Decimal("0.47"), "no_ask": Decimal("0.49")}]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "Polymarket Strike is None" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_price_sanity_fail(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("95000"),
            "current_price": Decimal("95500"),
            "prices": {"Up": Decimal("0.30"), "Down": Decimal("0.30")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("95500"),
            "markets": [{"strike": Decimal("95000"), "yes_bid": Decimal("0.50"), "yes_ask": Decimal("0.52"), "no_bid": Decimal("0.47"), "no_ask": Decimal("0.49")}]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "stale/incorrect" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_no_kalshi_markets(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("95000"),
            "current_price": Decimal("95500"),
            "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.47")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("95500"),
            "markets": []
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "No Kalshi markets found" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_arb_found_poly_gt_kalshi(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("96000"),
            "current_price": Decimal("96500"),
            "prices": {"Up": Decimal("0.60"), "Down": Decimal("0.35")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("96500"),
            "markets": [
                {"strike": Decimal("95000"), "yes_bid": Decimal("0.40"), "yes_ask": Decimal("0.42"), "no_bid": Decimal("0.55"), "no_ask": Decimal("0.58"), "subtitle": "$95,000 or above"},
            ]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "ARBITRAGE FOUND" in captured.out
        assert "Buy Poly DOWN + Kalshi YES" in captured.out
        assert "Est. Fees" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_arb_found_poly_lt_kalshi(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("94000"),
            "current_price": Decimal("94500"),
            "prices": {"Up": Decimal("0.35"), "Down": Decimal("0.60")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("94500"),
            "markets": [
                {"strike": Decimal("95000"), "yes_bid": Decimal("0.50"), "yes_ask": Decimal("0.58"), "no_bid": Decimal("0.40"), "no_ask": Decimal("0.42"), "subtitle": "$95,000 or above"},
            ]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "ARBITRAGE FOUND" in captured.out
        assert "Buy Poly UP + Kalshi NO" in captured.out
        assert "Est. Fees" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_arb_found_equal_strikes(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("95000"),
            "current_price": Decimal("95500"),
            "prices": {"Up": Decimal("0.45"), "Down": Decimal("0.47")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("95500"),
            "markets": [
                {"strike": Decimal("95000"), "yes_bid": Decimal("0.30"), "yes_ask": Decimal("0.35"), "no_bid": Decimal("0.30"), "no_ask": Decimal("0.35"), "subtitle": "$95,000 or above"},
            ]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "ARBITRAGE FOUND" in captured.out
        assert captured.out.count("ARBITRAGE FOUND") == 2

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_no_arb_found(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("95000"),
            "current_price": Decimal("95500"),
            "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.47")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("95500"),
            "markets": [
                {"strike": Decimal("95000"), "yes_bid": Decimal("0.50"), "yes_ask": Decimal("0.80"), "no_bid": Decimal("0.47"), "no_ask": Decimal("0.80"), "subtitle": "$95,000 or above"},
            ]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "No risk-free arbitrage found" in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_unpriced_legs_skipped(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("95000"),
            "current_price": Decimal("95500"),
            "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.47")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("95500"),
            "markets": [
                {"strike": Decimal("94000"), "yes_bid": Decimal("0"), "yes_ask": Decimal("0"), "no_bid": Decimal("0"), "no_ask": Decimal("0"), "subtitle": "$94,000 or above"},
            ]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "No risk-free arbitrage found" in captured.out
        assert "ARBITRAGE FOUND" not in captured.out

    @patch('arbitrage_bot.fetch_kalshi_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.fetch_polymarket_data_struct', new_callable=AsyncMock)
    @patch('arbitrage_bot.create_session', new_callable=AsyncMock)
    async def test_fee_profitable_label(self, mock_session, mock_poly, mock_kalshi, mock_binance, capsys):
        mock_session.return_value = AsyncMock()
        mock_session.return_value.close = AsyncMock()
        mock_poly.return_value = ({
            "price_to_beat": Decimal("96000"),
            "current_price": Decimal("96500"),
            "prices": {"Up": Decimal("0.55"), "Down": Decimal("0.40")},
            "depth": {"Up": Decimal("100"), "Down": Decimal("200")},
        }, None)
        mock_kalshi.return_value = ({
            "event_ticker": "TEST", "current_price": Decimal("96500"),
            "markets": [
                {"strike": Decimal("95000"), "yes_bid": Decimal("0.30"), "yes_ask": Decimal("0.32"), "no_bid": Decimal("0.65"), "no_ask": Decimal("0.68"), "subtitle": "$95,000 or above"},
            ]
        }, None)

        await check_arbitrage()
        captured = capsys.readouterr()
        assert "(PROFITABLE)" in captured.out


class TestMain:
    @patch('arbitrage_bot.check_arbitrage', new_callable=AsyncMock)
    def test_keyboard_interrupt(self, mock_check, capsys):
        mock_check.side_effect = KeyboardInterrupt()
        from arbitrage_bot import main
        main()
        captured = capsys.readouterr()
        assert "Stopping" in captured.out

    @patch('arbitrage_bot.check_arbitrage', new_callable=AsyncMock)
    def test_exception_continues(self, mock_check, capsys):
        mock_check.side_effect = [Exception("Network Error"), KeyboardInterrupt()]
        from arbitrage_bot import main
        main()
        captured = capsys.readouterr()
        assert "Error: Network Error" in captured.out
