"""Tests for execution API endpoints (/execute, /execution/status)."""
import sys
import os
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from httpx import AsyncClient, ASGITransport
from api import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.execution
class TestExecutionStatus:
    @pytest.mark.asyncio
    async def test_default_disabled(self, client):
        resp = await client.get("/execution/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["dry_run"] is True
        assert data["kalshi_environment"] == "demo"

    @pytest.mark.asyncio
    @patch("config.EXECUTION_ENABLED", True)
    @patch("config.EXECUTION_DRY_RUN", False)
    @patch("config.KALSHI_API_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2")
    async def test_production_enabled(self, client):
        resp = await client.get("/execution/status")
        data = resp.json()
        assert data["enabled"] is True
        assert data["dry_run"] is False
        assert data["kalshi_environment"] == "production"


@pytest.mark.execution
class TestExecuteEndpoint:
    @pytest.mark.asyncio
    async def test_disabled_returns_403(self, client):
        resp = await client.post("/execute", json={
            "poly_token_id": "tok1",
            "kalshi_ticker": "KXBTCD",
            "opportunity": {},
        })
        assert resp.status_code == 403
        assert "disabled" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("config.EXECUTION_ENABLED", True)
    async def test_missing_fields_returns_400(self, client):
        resp = await client.post("/execute", json={"poly_token_id": "tok1"})
        assert resp.status_code == 400
        assert "Missing required field" in resp.json()["error"]

    @pytest.mark.asyncio
    @patch("config.EXECUTION_ENABLED", True)
    @patch("config.EXECUTION_DRY_RUN", True)
    @patch("config.KALSHI_API_KEY_ID", "test-key")
    @patch("config.KALSHI_PRIVATE_KEY_PATH", "")
    @patch("config.POLYMARKET_HOST", "https://clob.polymarket.com")
    @patch("config.POLYMARKET_PRIVATE_KEY", "0xdeadbeef")
    @patch("config.POLYMARKET_CHAIN_ID", 137)
    @patch("config.DEFAULT_ORDER_SIZE", 10)
    async def test_dry_run_execution(self, client):
        """Test dry-run execution path with mocked client initialization."""
        from execution.models import ExecutionResult, OrderResult

        mock_result = ExecutionResult(
            status="dry_run",
            poly_result=OrderResult("dry-poly", "filled", Decimal("0.35"), 10, Decimal("0")),
            kalshi_result=OrderResult("dry-kalshi", "filled", Decimal("0.42"), 10, Decimal("0.02")),
            actual_pnl=Decimal("0.21"),
        )

        with patch("execution.kalshi_client.KalshiClient") as MockKalshi, \
             patch("execution.polymarket_client.PolymarketClient") as MockPoly, \
             patch("execution.engine.ExecutionEngine") as MockEngine:

            mock_kalshi = MagicMock()
            mock_kalshi.initialize.return_value = (True, None)
            MockKalshi.return_value = mock_kalshi

            mock_poly = MagicMock()
            mock_poly.initialize.return_value = (True, None)
            MockPoly.return_value = mock_poly

            mock_engine = MagicMock()
            mock_engine.build_execution_plan.return_value = MagicMock()
            mock_engine.execute = AsyncMock(return_value=mock_result)
            MockEngine.return_value = mock_engine

            resp = await client.post("/execute", json={
                "poly_token_id": "tok_down_456",
                "kalshi_ticker": "KXBTCD-26MAR2514",
                "opportunity": {
                    "poly_leg": "Down",
                    "kalshi_leg": "Yes",
                    "poly_cost": 0.35,
                    "kalshi_cost": 0.42,
                    "margin": 0.23,
                    "estimated_fees": 0.02,
                },
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dry_run"
        assert data["actual_pnl"] == 0.21

    @pytest.mark.asyncio
    @patch("config.EXECUTION_ENABLED", True)
    @patch("config.KALSHI_API_KEY_ID", "")
    @patch("config.KALSHI_PRIVATE_KEY_PATH", "")
    @patch("config.POLYMARKET_HOST", "https://clob.polymarket.com")
    @patch("config.POLYMARKET_PRIVATE_KEY", "")
    @patch("config.POLYMARKET_CHAIN_ID", 137)
    async def test_kalshi_init_failure(self, client):
        """Test failure when Kalshi client can't initialize."""
        with patch("execution.kalshi_client.KalshiClient") as MockKalshi:
            mock_kalshi = MagicMock()
            mock_kalshi.initialize.return_value = (False, "No private key provided")
            MockKalshi.return_value = mock_kalshi

            resp = await client.post("/execute", json={
                "poly_token_id": "tok1",
                "kalshi_ticker": "KXBTCD",
                "opportunity": {"poly_leg": "Down", "kalshi_leg": "Yes",
                               "poly_cost": 0.35, "kalshi_cost": 0.42,
                               "margin": 0.23, "estimated_fees": 0.02},
            })

        assert resp.status_code == 500
        assert "Kalshi client init failed" in resp.json()["error"]
