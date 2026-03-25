"""Kalshi API client for authenticated trading operations.

Supports order placement (limit, IOC), order status, cancellation,
and balance queries against both demo and production endpoints.
"""
import json
import logging
from decimal import Decimal
from typing import Optional

import aiohttp

from execution.kalshi_auth import (
    build_auth_headers,
    get_current_timestamp,
    load_private_key,
    load_private_key_from_string,
    sign_request,
)
from execution.models import OrderRequest, OrderResult

logger = logging.getLogger(__name__)


class KalshiClient:
    """Async client for the Kalshi trading API."""

    def __init__(
        self,
        base_url: str,
        api_key_id: str,
        private_key_pem: Optional[str] = None,
        private_key_path: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key_id = api_key_id
        self._private_key = None
        self._private_key_pem = private_key_pem
        self._private_key_path = private_key_path

    def initialize(self) -> tuple:
        """Load the private key. Must be called before making requests.

        Returns (success_bool, error) tuple.
        """
        if self._private_key_pem:
            key, err = load_private_key_from_string(self._private_key_pem)
        elif self._private_key_path:
            key, err = load_private_key(self._private_key_path)
        else:
            return False, "No private key provided (set private_key_pem or private_key_path)"

        if err:
            return False, err

        self._private_key = key
        return True, None

    async def _authenticated_request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        path: str,
        body: Optional[dict] = None,
    ) -> tuple:
        """Make an authenticated request to the Kalshi API.

        Returns (response_dict, error) tuple.
        """
        if not self._private_key:
            return None, "Client not initialized — call initialize() first"

        timestamp = get_current_timestamp()
        signature, sign_err = sign_request(self._private_key, timestamp, method.upper(), path)
        if sign_err:
            return None, sign_err

        headers = build_auth_headers(self.api_key_id, signature, timestamp)
        url = self.base_url + path

        try:
            kwargs = {"headers": headers}
            if body is not None:
                kwargs["data"] = json.dumps(body)

            async with session.request(method.upper(), url, **kwargs) as resp:
                if resp.status == 429:
                    return None, f"Rate limited (429) on {method.upper()} {path}"

                response_data = await resp.json()

                if resp.status >= 400:
                    error_msg = response_data.get("message", response_data.get("error", str(resp.status)))
                    return None, f"Kalshi API error ({resp.status}): {error_msg}"

                return response_data, None

        except aiohttp.ClientError as e:
            return None, f"HTTP error on {method.upper()} {path}: {e}"
        except Exception as e:
            return None, f"Unexpected error on {method.upper()} {path}: {e}"

    async def get_balance(self, session: aiohttp.ClientSession) -> tuple:
        """Get portfolio balance.

        Returns (Decimal_balance, error) tuple.
        """
        data, err = await self._authenticated_request(session, "GET", "/portfolio/balance")
        if err:
            return None, err

        try:
            balance = Decimal(str(data.get("balance", 0))) / Decimal("100")  # cents to dollars
            return balance, None
        except (KeyError, ValueError) as e:
            return None, f"Failed to parse balance: {e}"

    async def place_order(self, session: aiohttp.ClientSession, request: OrderRequest) -> tuple:
        """Place an order on Kalshi.

        Returns (OrderResult, error) tuple.
        """
        side_map = {"buy": "yes", "sell": "no"}
        body = {
            "action": "buy",
            "ticker": request.ticker,
            "type": "limit",
            "side": request.outcome.lower(),
            "count": request.size,
        }

        # Set price based on outcome
        if request.outcome.lower() == "yes":
            body["yes_price"] = int(request.price * 100)  # dollars to cents
        else:
            body["no_price"] = int(request.price * 100)

        # Set time_in_force for IOC orders
        if request.order_type == "ioc":
            body["time_in_force"] = "ioc"

        data, err = await self._authenticated_request(
            session, "POST", "/portfolio/orders", body=body
        )
        if err:
            return OrderResult(
                order_id="",
                status="error",
                error=err,
            ), None  # Return the result, not the error — caller inspects result.status

        try:
            order = data.get("order", data)
            order_id = order.get("order_id", "")
            status = order.get("status", "unknown")
            filled_size = order.get("filled_count", 0)

            # Map Kalshi status to our status
            status_map = {
                "resting": "open",
                "canceled": "cancelled",
                "executed": "filled",
                "pending": "open",
            }
            mapped_status = status_map.get(status, status)

            # Parse fill price if available
            filled_price = None
            if filled_size > 0:
                avg_price = order.get("average_fill_price")
                if avg_price is not None:
                    filled_price = Decimal(str(avg_price)) / Decimal("100")

            return OrderResult(
                order_id=order_id,
                status=mapped_status,
                filled_price=filled_price,
                filled_size=filled_size,
                raw_response=data,
            ), None

        except Exception as e:
            return OrderResult(
                order_id="",
                status="error",
                error=f"Failed to parse order response: {e}",
                raw_response=data,
            ), None

    async def get_order(self, session: aiohttp.ClientSession, order_id: str) -> tuple:
        """Get order status.

        Returns (order_dict, error) tuple.
        """
        return await self._authenticated_request(
            session, "GET", f"/portfolio/orders/{order_id}"
        )

    async def cancel_order(self, session: aiohttp.ClientSession, order_id: str) -> tuple:
        """Cancel an open order.

        Returns (success_bool, error) tuple.
        """
        data, err = await self._authenticated_request(
            session, "DELETE", f"/portfolio/orders/{order_id}"
        )
        if err:
            return False, err
        return True, None
