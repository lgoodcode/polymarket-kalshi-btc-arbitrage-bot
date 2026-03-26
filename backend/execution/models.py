"""Data models for the execution engine.

All financial values use Decimal for precision. These models are used
by the Kalshi client, Polymarket client, and execution engine.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
import time


@dataclass
class OrderRequest:
    """Request to place an order on an exchange."""
    platform: str          # "polymarket" | "kalshi"
    ticker: str            # market ticker (Kalshi) or token_id (Polymarket)
    side: str              # "buy" | "sell"
    outcome: str           # "yes"/"no" (Kalshi) or "Up"/"Down" (Polymarket)
    price: Decimal
    size: int
    order_type: str        # "gtc", "ioc", "fok"


@dataclass
class OrderResult:
    """Result of an order placement attempt."""
    order_id: str
    status: str            # "filled", "partial", "open", "cancelled", "rejected", "error"
    filled_price: Optional[Decimal] = None
    filled_size: int = 0
    fees: Decimal = Decimal("0")
    error: Optional[str] = None
    raw_response: Optional[dict] = field(default=None, repr=False)


@dataclass
class ExecutionPlan:
    """Plan for executing a two-leg arbitrage trade."""
    poly_order: OrderRequest
    kalshi_order: OrderRequest
    expected_margin: Decimal
    expected_fees: Decimal
    strategy: str = "maker_first"  # "maker_first" | "parallel"
    created_at: float = field(default_factory=time.time)


@dataclass
class ExecutionResult:
    """Result of executing an arbitrage trade."""
    status: str            # "success", "partial_fill", "failed", "dry_run"
    poly_result: Optional[OrderResult] = None
    kalshi_result: Optional[OrderResult] = None
    actual_pnl: Optional[Decimal] = None
    error: Optional[str] = None
