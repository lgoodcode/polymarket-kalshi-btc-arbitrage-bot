"""Tests for the cross-platform execution engine."""
import sys
import os
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from execution.engine import ExecutionEngine
from execution.models import (
    ExecutionPlan,
    ExecutionResult,
    OrderRequest,
    OrderResult,
)


@pytest.fixture
def mock_poly_client():
    client = MagicMock()
    client.place_order = AsyncMock()
    client.get_order = AsyncMock()
    client.cancel_order = AsyncMock()
    return client


@pytest.fixture
def mock_kalshi_client():
    client = MagicMock()
    client.place_order = AsyncMock()
    client.get_order = AsyncMock()
    client.cancel_order = AsyncMock()
    return client


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def engine(mock_poly_client, mock_kalshi_client):
    return ExecutionEngine(mock_poly_client, mock_kalshi_client, dry_run=False)


@pytest.fixture
def dry_run_engine(mock_poly_client, mock_kalshi_client):
    return ExecutionEngine(mock_poly_client, mock_kalshi_client, dry_run=True)


@pytest.fixture
def sample_opportunity():
    """An arbitrage opportunity as returned by run_arbitrage_checks()."""
    return {
        "kalshi_strike": 94000.0,
        "kalshi_yes": 0.42,
        "kalshi_no": 0.58,
        "type": "Poly > Kalshi",
        "poly_leg": "Down",
        "kalshi_leg": "Yes",
        "poly_cost": 0.35,
        "kalshi_cost": 0.42,
        "total_cost": 0.77,
        "is_arbitrage": True,
        "margin": 0.23,
        "estimated_fees": 0.02,
        "margin_after_fees": 0.21,
        "profitable_after_fees": True,
    }


@pytest.fixture
def sample_plan():
    """A pre-built execution plan."""
    return ExecutionPlan(
        poly_order=OrderRequest("polymarket", "tok_down", "buy", "Down", Decimal("0.35"), 10, "gtc"),
        kalshi_order=OrderRequest("kalshi", "KXBTCD-26MAR2514", "buy", "yes", Decimal("0.42"), 10, "ioc"),
        expected_margin=Decimal("0.23"),
        expected_fees=Decimal("0.02"),
        strategy="maker_first",
    )


@pytest.mark.execution
class TestBuildExecutionPlan:
    def test_basic_plan(self, engine, sample_opportunity):
        plan = engine.build_execution_plan(
            sample_opportunity,
            poly_token_id="tok_down_456",
            kalshi_ticker="KXBTCD-26MAR2514",
            size=10,
        )
        assert plan.poly_order.platform == "polymarket"
        assert plan.poly_order.ticker == "tok_down_456"
        assert plan.poly_order.outcome == "Down"
        assert plan.poly_order.price == Decimal("0.35")
        assert plan.poly_order.order_type == "gtc"
        assert plan.kalshi_order.platform == "kalshi"
        assert plan.kalshi_order.outcome == "yes"
        assert plan.kalshi_order.price == Decimal("0.42")
        assert plan.kalshi_order.order_type == "ioc"
        assert plan.expected_margin == Decimal("0.23")
        assert plan.strategy == "maker_first"

    def test_parallel_strategy(self, engine, sample_opportunity):
        plan = engine.build_execution_plan(
            sample_opportunity,
            poly_token_id="tok1",
            kalshi_ticker="KXBTCD",
            strategy="parallel",
        )
        assert plan.poly_order.order_type == "fok"
        assert plan.strategy == "parallel"


@pytest.mark.execution
class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated_result(self, dry_run_engine, sample_plan, mock_session):
        result = await dry_run_engine.execute(mock_session, sample_plan)
        assert result.status == "dry_run"
        assert result.poly_result is not None
        assert result.kalshi_result is not None
        assert result.actual_pnl == Decimal("0.21")  # 0.23 margin - 0.02 fees
        assert result.poly_result.order_id == "dry-run-poly"
        assert result.kalshi_result.order_id == "dry-run-kalshi"

    @pytest.mark.asyncio
    async def test_dry_run_no_real_orders(self, dry_run_engine, sample_plan, mock_session):
        await dry_run_engine.execute(mock_session, sample_plan)
        # No actual client calls should be made
        dry_run_engine.poly_client.place_order.assert_not_called()
        dry_run_engine.kalshi_client.place_order.assert_not_called()


@pytest.mark.execution
class TestMarginCheck:
    @pytest.mark.asyncio
    async def test_rejects_below_minimum_margin(self, engine, mock_session):
        plan = ExecutionPlan(
            poly_order=OrderRequest("polymarket", "tok1", "buy", "Down", Decimal("0.49"), 10, "gtc"),
            kalshi_order=OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.50"), 10, "ioc"),
            expected_margin=Decimal("0.01"),
            expected_fees=Decimal("0.008"),
            strategy="maker_first",
        )

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.005")):
            with patch("config.POLY_FILL_TIMEOUT", 30):
                with patch("config.POLY_FILL_POLL_INTERVAL", 1.0):
                    result = await engine.execute(mock_session, plan)

        assert result.status == "failed"
        assert "below minimum" in result.error

    @pytest.mark.asyncio
    async def test_margin_exactly_at_minimum_passes(self, engine, mock_session, sample_plan, mock_poly_client, mock_kalshi_client):
        """Margin at exactly the minimum should proceed."""
        # sample_plan has margin=0.23, fees=0.02, net=0.21 > 0.005
        mock_poly_client.place_order.return_value = (
            OrderResult("p1", "open", filled_size=0), None
        )
        mock_poly_client.get_order.return_value = ({"status": "MATCHED"}, None)
        mock_kalshi_client.place_order.return_value = (
            OrderResult("k1", "filled", Decimal("0.42"), 10, Decimal("0.02")), None
        )

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.005")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, sample_plan)

        assert result.status == "success"


@pytest.mark.execution
class TestMakerFirstExecution:
    @pytest.mark.asyncio
    async def test_happy_path(self, engine, mock_session, sample_plan, mock_poly_client, mock_kalshi_client):
        """Both legs fill successfully."""
        mock_poly_client.place_order.return_value = (
            OrderResult("p1", "open", filled_size=0), None
        )
        mock_poly_client.get_order.return_value = ({"status": "MATCHED"}, None)
        mock_kalshi_client.place_order.return_value = (
            OrderResult("k1", "filled", Decimal("0.42"), 10, Decimal("0.02")), None
        )

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, sample_plan)

        assert result.status == "success"
        assert result.poly_result.status == "filled"
        assert result.kalshi_result.status == "filled"
        assert result.actual_pnl is not None
        assert result.actual_pnl > 0

    @pytest.mark.asyncio
    async def test_poly_order_rejected(self, engine, mock_session, sample_plan, mock_poly_client):
        """Polymarket rejects the order."""
        mock_poly_client.place_order.return_value = (
            OrderResult("", "rejected", error="Insufficient funds"), None
        )

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, sample_plan)

        assert result.status == "failed"
        assert "Polymarket order failed" in result.error

    @pytest.mark.asyncio
    async def test_poly_timeout_cancels_order(self, engine, mock_session, sample_plan, mock_poly_client):
        """Polymarket order times out — should be cancelled."""
        mock_poly_client.place_order.return_value = (
            OrderResult("p1", "open", filled_size=0), None
        )
        # Never returns MATCHED
        mock_poly_client.get_order.return_value = ({"status": "LIVE"}, None)
        mock_poly_client.cancel_order.return_value = (True, None)

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 0.3):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, sample_plan)

        assert result.status == "failed"
        assert "timed out" in result.error
        mock_poly_client.cancel_order.assert_called_once_with("p1")

    @pytest.mark.asyncio
    async def test_kalshi_fails_triggers_rollback(self, engine, mock_session, sample_plan, mock_poly_client, mock_kalshi_client):
        """Polymarket fills but Kalshi rejects — rollback attempted."""
        mock_poly_client.place_order.return_value = (
            OrderResult("p1", "open", filled_size=0), None
        )
        mock_poly_client.get_order.return_value = ({"status": "MATCHED"}, None)
        mock_kalshi_client.place_order.return_value = (
            OrderResult("", "rejected", error="No liquidity"), None
        )
        mock_poly_client.cancel_order.return_value = (True, None)

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, sample_plan)

        assert result.status == "partial_fill"
        assert "Kalshi leg failed" in result.error
        mock_poly_client.cancel_order.assert_called_once()


@pytest.mark.execution
class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_both_fill(self, engine, mock_session, mock_poly_client, mock_kalshi_client):
        plan = ExecutionPlan(
            poly_order=OrderRequest("polymarket", "tok1", "buy", "Down", Decimal("0.35"), 10, "fok"),
            kalshi_order=OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.42"), 10, "ioc"),
            expected_margin=Decimal("0.23"),
            expected_fees=Decimal("0.02"),
            strategy="parallel",
        )

        mock_poly_client.place_order.return_value = (
            OrderResult("p1", "filled", Decimal("0.35"), 10, Decimal("0")), None
        )
        mock_kalshi_client.place_order.return_value = (
            OrderResult("k1", "filled", Decimal("0.42"), 10, Decimal("0.02")), None
        )

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, plan)

        assert result.status == "success"
        assert result.actual_pnl > 0

    @pytest.mark.asyncio
    async def test_poly_fills_kalshi_fails(self, engine, mock_session, mock_poly_client, mock_kalshi_client):
        plan = ExecutionPlan(
            poly_order=OrderRequest("polymarket", "tok1", "buy", "Down", Decimal("0.35"), 10, "fok"),
            kalshi_order=OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.42"), 10, "ioc"),
            expected_margin=Decimal("0.23"),
            expected_fees=Decimal("0.02"),
            strategy="parallel",
        )

        mock_poly_client.place_order.return_value = (
            OrderResult("p1", "filled", Decimal("0.35"), 10, Decimal("0")), None
        )
        mock_kalshi_client.place_order.return_value = (
            OrderResult("", "rejected", error="No liquidity"), None
        )
        mock_poly_client.cancel_order.return_value = (True, None)

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, plan)

        assert result.status == "partial_fill"
        assert "Kalshi leg failed" in result.error

    @pytest.mark.asyncio
    async def test_neither_fills(self, engine, mock_session, mock_poly_client, mock_kalshi_client):
        plan = ExecutionPlan(
            poly_order=OrderRequest("polymarket", "tok1", "buy", "Down", Decimal("0.35"), 10, "fok"),
            kalshi_order=OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.42"), 10, "ioc"),
            expected_margin=Decimal("0.23"),
            expected_fees=Decimal("0.02"),
            strategy="parallel",
        )

        mock_poly_client.place_order.return_value = (
            OrderResult("", "rejected"), None
        )
        mock_kalshi_client.place_order.return_value = (
            OrderResult("", "cancelled"), None
        )

        with patch("config.MIN_MARGIN_AFTER_FEES", Decimal("0.001")):
            with patch("config.POLY_FILL_TIMEOUT", 1):
                with patch("config.POLY_FILL_POLL_INTERVAL", 0.1):
                    result = await engine.execute(mock_session, plan)

        assert result.status == "failed"
        assert "Neither leg filled" in result.error


@pytest.mark.execution
class TestCalculatePnl:
    def test_basic_pnl(self, engine):
        poly = OrderResult("p1", "filled", Decimal("0.35"), 10, Decimal("0"))
        kalshi = OrderResult("k1", "filled", Decimal("0.42"), 10, Decimal("0.02"))
        pnl = engine._calculate_pnl(poly, kalshi)
        # payout = 1.00 * 10 = 10.00
        # cost = (0.35 * 10) + (0.42 * 10) = 3.50 + 4.20 = 7.70
        # fees = 0 + 0.02 = 0.02
        # pnl = 10.00 - 7.70 - 0.02 = 2.28
        assert pnl == Decimal("2.28")
