"""Tests for Polymarket trading client."""
import sys
import os
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from execution.polymarket_client import PolymarketClient
from execution.models import OrderRequest, OrderResult


@pytest.fixture
def mock_clob_client():
    """Create a mock ClobClient."""
    client = MagicMock()
    client.derive_api_key.return_value = {
        "apiKey": "test-api-key",
        "secret": "test-secret",
        "passphrase": "test-passphrase",
    }
    client.set_api_creds = MagicMock()
    client.create_order = MagicMock(return_value={"mock": "signed_order"})
    client.post_order = MagicMock(return_value={"success": True, "orderID": "default-id"})
    return client


@pytest.fixture
def poly_client(mock_clob_client):
    """Create an initialized PolymarketClient with mocked SDK."""
    client = PolymarketClient(
        host="https://clob.polymarket.com",
        private_key="0xdeadbeef",
        chain_id=137,
    )
    # Manually set internal state as if initialized
    client._client = mock_clob_client
    client._initialized = True
    return client


@pytest.mark.execution
class TestPolymarketClientInit:
    @patch("py_clob_client.client.ClobClient")
    def test_init_derives_api_keys(self, MockClobClass):
        mock_instance = MagicMock()
        mock_instance.derive_api_key.return_value = {
            "apiKey": "key", "secret": "sec", "passphrase": "pass",
        }
        MockClobClass.return_value = mock_instance

        client = PolymarketClient(
            host="https://clob.polymarket.com",
            private_key="0xdeadbeef",
        )
        ok, err = client.initialize()
        assert ok is True
        assert err is None
        assert client._initialized is True
        mock_instance.derive_api_key.assert_called_once()
        mock_instance.set_api_creds.assert_called_once()

    @patch("py_clob_client.client.ClobClient")
    def test_init_failure(self, MockClobClass):
        MockClobClass.side_effect = Exception("Bad key")

        client = PolymarketClient(
            host="https://clob.polymarket.com",
            private_key="invalid",
        )
        ok, err = client.initialize()
        assert ok is False
        assert "Failed to initialize" in err


@pytest.mark.execution
class TestGetFeeRate:
    @pytest.mark.asyncio
    async def test_success(self, poly_client):
        mock_session = MagicMock()
        fee_data = {"maker": "0", "taker": "0.0624"}

        with patch("http_utils.fetch_json", new_callable=AsyncMock, return_value=fee_data):
            rates, err = await poly_client.get_fee_rate(mock_session, "token_123")

        assert err is None
        assert rates["maker"] == Decimal("0")
        assert rates["taker"] == Decimal("0.0624")

    @pytest.mark.asyncio
    async def test_error(self, poly_client):
        mock_session = MagicMock()

        with patch("http_utils.fetch_json", new_callable=AsyncMock, side_effect=Exception("timeout")):
            rates, err = await poly_client.get_fee_rate(mock_session, "token_123")

        assert rates is None
        assert "Failed to fetch fee rate" in err


@pytest.mark.execution
class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_gtc_order_success(self, poly_client):
        poly_client._client.post_order.return_value = {
            "success": True,
            "orderID": "poly-ord-123",
        }

        req = OrderRequest(
            platform="polymarket",
            ticker="token_up_123",
            side="buy",
            outcome="Up",
            price=Decimal("0.47"),
            size=20,
            order_type="gtc",
        )

        result, err = await poly_client.place_order(req)
        assert err is None
        assert result.order_id == "poly-ord-123"
        assert result.status == "open"
        assert result.filled_size == 0  # GTC starts unfilled

    @pytest.mark.asyncio
    async def test_fok_order_success(self, poly_client):
        poly_client._client.post_order.return_value = {
            "success": True,
            "orderID": "poly-ord-456",
        }

        req = OrderRequest(
            platform="polymarket",
            ticker="token_down_456",
            side="buy",
            outcome="Down",
            price=Decimal("0.35"),
            size=10,
            order_type="fok",
        )

        result, err = await poly_client.place_order(req)
        assert err is None
        assert result.status == "filled"
        assert result.filled_size == 10
        assert result.filled_price == Decimal("0.35")

    @pytest.mark.asyncio
    async def test_order_rejected(self, poly_client):
        poly_client._client.post_order.return_value = {
            "success": False,
            "errorMsg": "Insufficient funds",
        }

        req = OrderRequest("polymarket", "tok1", "buy", "Up", Decimal("0.50"), 10, "gtc")

        result, err = await poly_client.place_order(req)
        assert err is None
        assert result.status == "rejected"
        assert "Insufficient funds" in result.error

    @pytest.mark.asyncio
    async def test_unsupported_order_type(self, poly_client):
        req = OrderRequest("polymarket", "tok1", "buy", "Up", Decimal("0.50"), 10, "ioc")

        result, err = await poly_client.place_order(req)
        assert err is None
        assert result.status == "error"
        assert "Unsupported order type" in result.error

    @pytest.mark.asyncio
    async def test_sdk_exception(self, poly_client):
        poly_client._client.create_order.side_effect = Exception("SDK crash")

        req = OrderRequest("polymarket", "tok1", "buy", "Up", Decimal("0.50"), 10, "gtc")

        result, err = await poly_client.place_order(req)
        assert err is None
        assert result.status == "error"
        assert "SDK crash" in result.error

    @pytest.mark.asyncio
    async def test_order_args_side_mapping(self, poly_client):
        """Verify BUY/SELL side strings are sent correctly."""
        poly_client._client.post_order.return_value = {"success": True, "orderID": "test"}

        req = OrderRequest("polymarket", "tok1", "sell", "Down", Decimal("0.50"), 10, "gtc")
        await poly_client.place_order(req)

        # Check what was passed to create_order
        call_args = poly_client._client.create_order.call_args
        order_args = call_args[0][0]
        assert order_args.side == "SELL"

    @pytest.mark.asyncio
    async def test_uses_correct_order_type(self, poly_client):
        """Verify FOK order type is passed to post_order."""
        from py_clob_client.clob_types import OrderType
        poly_client._client.post_order.return_value = {"success": True, "orderID": "test"}

        req = OrderRequest("polymarket", "tok1", "buy", "Up", Decimal("0.50"), 10, "fok")
        await poly_client.place_order(req)

        # post_order should be called with FOK type
        call_args = poly_client._client.post_order.call_args
        assert call_args[0][1] == OrderType.FOK


@pytest.mark.execution
class TestGetOrder:
    @pytest.mark.asyncio
    async def test_success(self, poly_client):
        poly_client._client.get_order = MagicMock(return_value={
            "id": "poly-123",
            "status": "MATCHED",
        })

        data, err = await poly_client.get_order("poly-123")
        assert err is None
        assert data["status"] == "MATCHED"

    @pytest.mark.asyncio
    async def test_not_initialized(self):
        client = PolymarketClient("https://clob.polymarket.com", "0xdeadbeef")
        data, err = await client.get_order("poly-123")
        assert data is None
        assert "not initialized" in err


@pytest.mark.execution
class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_success(self, poly_client):
        poly_client._client.cancel = MagicMock(return_value=None)

        ok, err = await poly_client.cancel_order("poly-123")
        assert ok is True
        assert err is None

    @pytest.mark.asyncio
    async def test_cancel_failure(self, poly_client):
        poly_client._client.cancel = MagicMock(side_effect=Exception("Not found"))

        ok, err = await poly_client.cancel_order("poly-nonexistent")
        assert ok is False
        assert "Not found" in err
