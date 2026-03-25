"""Tests for Kalshi trading client."""
import sys
import os
import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from execution.kalshi_client import KalshiClient
from execution.models import OrderRequest, OrderResult

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def test_private_key():
    """Generate a test RSA private key PEM string."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode()


@pytest.fixture
def kalshi_client(test_private_key):
    """Create a KalshiClient initialized with a test key."""
    client = KalshiClient(
        base_url="https://demo-api.kalshi.co/trade-api/v2",
        api_key_id="test-key-id",
        private_key_pem=test_private_key,
    )
    ok, err = client.initialize()
    assert ok, f"Client init failed: {err}"
    return client


class MockResponse:
    """Mock aiohttp response with async context manager support."""
    def __init__(self, json_data, status=200):
        self._json_data = json_data
        self.status = status
        self.request_info = MagicMock()
        self.history = ()

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.execution
class TestKalshiClientInit:
    def test_init_with_pem_string(self, test_private_key):
        client = KalshiClient(
            base_url="https://demo-api.kalshi.co/trade-api/v2",
            api_key_id="test",
            private_key_pem=test_private_key,
        )
        ok, err = client.initialize()
        assert ok is True
        assert err is None

    def test_init_no_key(self):
        client = KalshiClient(
            base_url="https://demo-api.kalshi.co/trade-api/v2",
            api_key_id="test",
        )
        ok, err = client.initialize()
        assert ok is False
        assert "No private key" in err

    def test_init_invalid_pem(self):
        client = KalshiClient(
            base_url="https://demo-api.kalshi.co/trade-api/v2",
            api_key_id="test",
            private_key_pem="not-a-valid-key",
        )
        ok, err = client.initialize()
        assert ok is False
        assert err is not None


@pytest.mark.execution
class TestGetBalance:
    @pytest.mark.asyncio
    async def test_success(self, kalshi_client):
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse({"balance": 10000}))

        balance, err = await kalshi_client.get_balance(mock_session)
        assert err is None
        assert balance == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_api_error(self, kalshi_client):
        mock_session = MagicMock()
        mock_session.request = MagicMock(
            return_value=MockResponse({"message": "Unauthorized"}, status=401)
        )

        balance, err = await kalshi_client.get_balance(mock_session)
        assert balance is None
        assert "401" in err


@pytest.mark.execution
class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_limit_order_filled(self, kalshi_client):
        order_response = {
            "order": {
                "order_id": "ord-123",
                "status": "executed",
                "filled_count": 10,
                "average_fill_price": 55,
            }
        }
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse(order_response))

        req = OrderRequest(
            platform="kalshi",
            ticker="KXBTCD-26MAR2514",
            side="buy",
            outcome="yes",
            price=Decimal("0.55"),
            size=10,
            order_type="gtc",
        )

        result, err = await kalshi_client.place_order(mock_session, req)
        assert err is None
        assert result.order_id == "ord-123"
        assert result.status == "filled"
        assert result.filled_size == 10
        assert result.filled_price == Decimal("0.55")

    @pytest.mark.asyncio
    async def test_ioc_order_no_fill(self, kalshi_client):
        order_response = {
            "order": {
                "order_id": "ord-456",
                "status": "canceled",
                "filled_count": 0,
            }
        }
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse(order_response))

        req = OrderRequest(
            platform="kalshi",
            ticker="KXBTCD-26MAR2514",
            side="buy",
            outcome="no",
            price=Decimal("0.42"),
            size=10,
            order_type="ioc",
        )

        result, err = await kalshi_client.place_order(mock_session, req)
        assert err is None
        assert result.status == "cancelled"
        assert result.filled_size == 0

    @pytest.mark.asyncio
    async def test_api_error_returns_error_result(self, kalshi_client):
        mock_session = MagicMock()
        mock_session.request = MagicMock(
            return_value=MockResponse({"message": "Insufficient balance"}, status=400)
        )

        req = OrderRequest(
            platform="kalshi",
            ticker="KXBTCD-26MAR2514",
            side="buy",
            outcome="yes",
            price=Decimal("0.55"),
            size=10,
            order_type="gtc",
        )

        result, err = await kalshi_client.place_order(mock_session, req)
        assert err is None  # Error is in result, not second tuple element
        assert result.status == "error"
        assert "Insufficient balance" in result.error

    @pytest.mark.asyncio
    async def test_yes_price_sent_for_yes_outcome(self, kalshi_client):
        """Verify correct price field is used based on outcome."""
        order_response = {"order": {"order_id": "ord-789", "status": "resting", "filled_count": 0}}
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse(order_response))

        req = OrderRequest(
            platform="kalshi",
            ticker="KXBTCD",
            side="buy",
            outcome="yes",
            price=Decimal("0.55"),
            size=5,
            order_type="gtc",
        )

        await kalshi_client.place_order(mock_session, req)

        # Check what was sent in the request body
        call_args = mock_session.request.call_args
        body = json.loads(call_args[1]["data"])
        assert body["yes_price"] == 55
        assert "no_price" not in body
        assert body["side"] == "yes"
        assert body["count"] == 5

    @pytest.mark.asyncio
    async def test_no_price_sent_for_no_outcome(self, kalshi_client):
        order_response = {"order": {"order_id": "ord-790", "status": "resting", "filled_count": 0}}
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse(order_response))

        req = OrderRequest(
            platform="kalshi",
            ticker="KXBTCD",
            side="buy",
            outcome="no",
            price=Decimal("0.42"),
            size=10,
            order_type="ioc",
        )

        await kalshi_client.place_order(mock_session, req)

        call_args = mock_session.request.call_args
        body = json.loads(call_args[1]["data"])
        assert body["no_price"] == 42
        assert "yes_price" not in body
        assert body["time_in_force"] == "ioc"

    @pytest.mark.asyncio
    async def test_resting_order_maps_to_open(self, kalshi_client):
        order_response = {"order": {"order_id": "ord-800", "status": "resting", "filled_count": 0}}
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse(order_response))

        req = OrderRequest("kalshi", "KXBTCD", "buy", "yes", Decimal("0.55"), 10, "gtc")
        result, _ = await kalshi_client.place_order(mock_session, req)
        assert result.status == "open"


@pytest.mark.execution
class TestGetOrder:
    @pytest.mark.asyncio
    async def test_success(self, kalshi_client):
        order_data = {"order_id": "ord-123", "status": "executed", "filled_count": 10}
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse(order_data))

        data, err = await kalshi_client.get_order(mock_session, "ord-123")
        assert err is None
        assert data["order_id"] == "ord-123"


@pytest.mark.execution
class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_success(self, kalshi_client):
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=MockResponse({}))

        ok, err = await kalshi_client.cancel_order(mock_session, "ord-123")
        assert ok is True
        assert err is None

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, kalshi_client):
        mock_session = MagicMock()
        mock_session.request = MagicMock(
            return_value=MockResponse({"message": "Order not found"}, status=404)
        )

        ok, err = await kalshi_client.cancel_order(mock_session, "ord-nonexistent")
        assert ok is False
        assert "404" in err


@pytest.mark.execution
class TestUninitializedClient:
    @pytest.mark.asyncio
    async def test_request_without_init(self):
        client = KalshiClient(
            base_url="https://demo-api.kalshi.co/trade-api/v2",
            api_key_id="test",
            private_key_pem="not-loaded-yet",
        )
        # Don't call initialize()
        mock_session = MagicMock()
        balance, err = await client.get_balance(mock_session)
        assert balance is None
        assert "not initialized" in err
