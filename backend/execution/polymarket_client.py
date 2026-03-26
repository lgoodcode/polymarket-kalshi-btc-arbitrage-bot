"""Polymarket CLOB client for authenticated trading operations.

Wraps py-clob-client SDK for order placement, cancellation, and fee rate queries.
SDK calls are synchronous, so we use asyncio.to_thread() for async compatibility.
"""
import asyncio
import logging
from decimal import Decimal
from typing import Optional

from execution.models import OrderRequest, OrderResult

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Async wrapper around py-clob-client SDK."""

    def __init__(self, host: str, private_key: str, chain_id: int = 137):
        self.host = host
        self._private_key = private_key
        self._chain_id = chain_id
        self._client = None
        self._initialized = False

    def initialize(self) -> tuple:
        """Initialize the SDK client and derive API credentials.

        Returns (success_bool, error) tuple.
        """
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            self._client = ClobClient(
                self.host,
                key=self._private_key,
                chain_id=self._chain_id,
                signature_type=2,  # POLY_GNOSIS_SAFE
            )

            # Derive API credentials from private key
            creds = self._client.derive_api_key()
            self._client.set_api_creds(ApiCreds(
                api_key=creds["apiKey"],
                api_secret=creds["secret"],
                api_passphrase=creds["passphrase"],
            ))

            self._initialized = True
            return True, None

        except ImportError:
            return False, "py-clob-client is not installed. Run: pip install py-clob-client"
        except Exception as e:
            return False, f"Failed to initialize Polymarket client: {e}"

    async def get_fee_rate(self, session, token_id: str) -> tuple:
        """Fetch dynamic fee rates for a token.

        Uses raw aiohttp (not the SDK) for consistency with existing http patterns.

        Returns (dict with 'maker' and 'taker' Decimal rates, error) tuple.
        """
        try:
            from http_utils import fetch_json
            from config import POLYMARKET_FEE_RATE_URL

            data = await fetch_json(session, POLYMARKET_FEE_RATE_URL, params={"token_id": token_id})
            maker = Decimal(str(data.get("maker", "0")))
            taker = Decimal(str(data.get("taker", "0")))
            return {"maker": maker, "taker": taker}, None
        except Exception as e:
            return None, f"Failed to fetch fee rate: {e}"

    async def place_order(self, request: OrderRequest) -> tuple:
        """Place an order on Polymarket via the SDK.

        Returns (OrderResult, error) tuple.
        """
        if not self._initialized or self._client is None:
            return OrderResult(
                order_id="",
                status="error",
                error="Client not initialized — call initialize() first",
            ), None

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType

            # Map our order type to SDK order type
            order_type_map = {
                "gtc": OrderType.GTC,
                "fok": OrderType.FOK,
            }
            sdk_order_type = order_type_map.get(request.order_type)
            if sdk_order_type is None:
                return OrderResult(
                    order_id="",
                    status="error",
                    error=f"Unsupported order type for Polymarket: {request.order_type}",
                ), None

            side = "BUY" if request.side == "buy" else "SELL"

            order_args = OrderArgs(
                token_id=request.ticker,
                price=float(request.price),
                size=float(request.size),
                side=side,
            )

            # SDK is synchronous — run in thread pool
            # Use create_order + post_order to control order type
            def _place():
                signed_order = self._client.create_order(order_args)
                return self._client.post_order(signed_order, sdk_order_type)

            response = await asyncio.to_thread(_place)

            if not response or not response.get("success"):
                error_msg = response.get("errorMsg", "Order rejected") if response else "No response"
                return OrderResult(
                    order_id="",
                    status="rejected",
                    error=error_msg,
                    raw_response=response,
                ), None

            order_id = response.get("orderID", "")

            # Parse actual fill data from response when available
            if request.order_type == "fok":
                filled_size = int(response.get("filledSize", request.size))
                avg_price = response.get("averagePrice")
                filled_price = Decimal(str(avg_price)) if avg_price is not None else request.price
                status = "filled"
            else:
                filled_size = 0
                filled_price = None
                status = "open"

            return OrderResult(
                order_id=order_id,
                status=status,
                filled_size=filled_size,
                filled_price=filled_price,
                raw_response=response,
            ), None

        except Exception as e:
            return OrderResult(
                order_id="",
                status="error",
                error=f"Polymarket order failed: {e}",
            ), None

    async def get_order(self, order_id: str) -> tuple:
        """Get order status from Polymarket.

        Returns (order_dict, error) tuple.
        """
        if not self._initialized or self._client is None:
            return None, "Client not initialized"

        try:
            result = await asyncio.to_thread(self._client.get_order, order_id)
            return result, None
        except Exception as e:
            return None, f"Failed to get order: {e}"

    async def cancel_order(self, order_id: str) -> tuple:
        """Cancel an open order on Polymarket.

        Returns (success_bool, error) tuple.
        """
        if not self._initialized or self._client is None:
            return False, "Client not initialized"

        try:
            result = await asyncio.to_thread(self._client.cancel, order_id)
            return True, None
        except Exception as e:
            return False, f"Failed to cancel order: {e}"
