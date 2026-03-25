"""Tests for execution data models."""
import sys
import os
import pytest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from execution.models import OrderRequest, OrderResult, ExecutionPlan, ExecutionResult


@pytest.mark.execution
class TestOrderRequest:
    def test_construction(self):
        req = OrderRequest(
            platform="kalshi",
            ticker="KXBTCD-26MAR2514",
            side="buy",
            outcome="yes",
            price=Decimal("0.55"),
            size=10,
            order_type="ioc",
        )
        assert req.platform == "kalshi"
        assert req.price == Decimal("0.55")
        assert req.size == 10
        assert req.order_type == "ioc"

    def test_polymarket_order(self):
        req = OrderRequest(
            platform="polymarket",
            ticker="token_up_123",
            side="buy",
            outcome="Up",
            price=Decimal("0.47"),
            size=20,
            order_type="gtc",
        )
        assert req.platform == "polymarket"
        assert req.outcome == "Up"
        assert req.order_type == "gtc"


@pytest.mark.execution
class TestOrderResult:
    def test_defaults(self):
        result = OrderResult(order_id="abc123", status="filled")
        assert result.filled_price is None
        assert result.filled_size == 0
        assert result.fees == Decimal("0")
        assert result.error is None
        assert result.raw_response is None

    def test_filled_order(self):
        result = OrderResult(
            order_id="abc123",
            status="filled",
            filled_price=Decimal("0.55"),
            filled_size=10,
            fees=Decimal("0.02"),
        )
        assert result.filled_price == Decimal("0.55")
        assert result.filled_size == 10
        assert result.fees == Decimal("0.02")

    def test_error_order(self):
        result = OrderResult(
            order_id="",
            status="error",
            error="Connection timeout",
        )
        assert result.status == "error"
        assert result.error == "Connection timeout"


@pytest.mark.execution
class TestExecutionPlan:
    def test_construction(self):
        poly = OrderRequest("polymarket", "tok1", "buy", "Down", Decimal("0.35"), 10, "gtc")
        kalshi = OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.42"), 10, "ioc")
        plan = ExecutionPlan(
            poly_order=poly,
            kalshi_order=kalshi,
            expected_margin=Decimal("0.23"),
            expected_fees=Decimal("0.02"),
        )
        assert plan.strategy == "maker_first"
        assert plan.expected_margin == Decimal("0.23")
        assert plan.created_at > 0

    def test_parallel_strategy(self):
        poly = OrderRequest("polymarket", "tok1", "buy", "Down", Decimal("0.35"), 10, "fok")
        kalshi = OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.42"), 10, "ioc")
        plan = ExecutionPlan(
            poly_order=poly,
            kalshi_order=kalshi,
            expected_margin=Decimal("0.23"),
            expected_fees=Decimal("0.02"),
            strategy="parallel",
        )
        assert plan.strategy == "parallel"


@pytest.mark.execution
class TestExecutionResult:
    def test_defaults(self):
        result = ExecutionResult(status="dry_run")
        assert result.poly_result is None
        assert result.kalshi_result is None
        assert result.actual_pnl is None
        assert result.error is None

    def test_success(self):
        poly_res = OrderResult("p1", "filled", Decimal("0.35"), 10, Decimal("0"))
        kalshi_res = OrderResult("k1", "filled", Decimal("0.42"), 10, Decimal("0.02"))
        result = ExecutionResult(
            status="success",
            poly_result=poly_res,
            kalshi_result=kalshi_res,
            actual_pnl=Decimal("0.21"),
        )
        assert result.status == "success"
        assert result.actual_pnl == Decimal("0.21")

    def test_partial_fill(self):
        poly_res = OrderResult("p1", "filled", Decimal("0.35"), 10, Decimal("0"))
        result = ExecutionResult(
            status="partial_fill",
            poly_result=poly_res,
            error="Kalshi IOC rejected: no liquidity",
        )
        assert result.status == "partial_fill"
        assert result.error is not None
