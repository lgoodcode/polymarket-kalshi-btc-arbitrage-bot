"""Cross-platform arbitrage execution engine.

Orchestrates the maker-first strategy: GTC on Polymarket (zero maker fee),
then IOC on Kalshi when the Polymarket order fills. Supports parallel
execution as a fallback. Dry-run mode by default.
"""
import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional

from execution.models import (
    ExecutionPlan,
    ExecutionResult,
    OrderRequest,
    OrderResult,
)

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Cross-platform arbitrage execution orchestrator."""

    def __init__(self, poly_client, kalshi_client, dry_run: bool = True):
        self.poly_client = poly_client
        self.kalshi_client = kalshi_client
        self.dry_run = dry_run

    def build_execution_plan(
        self,
        opportunity: dict,
        poly_token_id: str,
        kalshi_ticker: str,
        size: int = 10,
        strategy: str = "maker_first",
    ) -> ExecutionPlan:
        """Convert an opportunity dict from run_arbitrage_checks() into an ExecutionPlan.

        The opportunity dict has keys: poly_leg, kalshi_leg, poly_cost, kalshi_cost,
        margin, estimated_fees, etc.
        """
        poly_leg = opportunity["poly_leg"]     # "Up" or "Down"
        kalshi_leg = opportunity["kalshi_leg"]  # "Yes" or "No"
        poly_cost = Decimal(str(opportunity["poly_cost"]))
        kalshi_cost = Decimal(str(opportunity["kalshi_cost"]))
        margin = Decimal(str(opportunity["margin"]))
        fees = Decimal(str(opportunity.get("estimated_fees", 0)))

        poly_order_type = "gtc" if strategy == "maker_first" else "fok"
        kalshi_order_type = "ioc"

        poly_order = OrderRequest(
            platform="polymarket",
            ticker=poly_token_id,
            side="buy",
            outcome=poly_leg,
            price=poly_cost,
            size=size,
            order_type=poly_order_type,
        )

        kalshi_order = OrderRequest(
            platform="kalshi",
            ticker=kalshi_ticker,
            side="buy",
            outcome=kalshi_leg.lower(),  # "yes" or "no"
            price=kalshi_cost,
            size=size,
            order_type=kalshi_order_type,
        )

        return ExecutionPlan(
            poly_order=poly_order,
            kalshi_order=kalshi_order,
            expected_margin=margin,
            expected_fees=fees,
            strategy=strategy,
        )

    async def execute(self, session, plan: ExecutionPlan) -> ExecutionResult:
        """Execute a two-leg arbitrage trade.

        Maker-first strategy:
        1. Place GTC (maker) on Polymarket
        2. Poll for fill (with timeout)
        3. On fill: place IOC on Kalshi
        4. If Kalshi fails: attempt rollback

        In dry_run mode: return simulated result without placing orders.
        """
        from config import MIN_MARGIN_AFTER_FEES, POLY_FILL_TIMEOUT, POLY_FILL_POLL_INTERVAL

        # Margin check
        net_margin = plan.expected_margin - plan.expected_fees
        if net_margin < MIN_MARGIN_AFTER_FEES:
            return ExecutionResult(
                status="failed",
                error=f"Margin after fees ({net_margin}) below minimum ({MIN_MARGIN_AFTER_FEES})",
            )

        if self.dry_run:
            return self._simulate(plan)

        if plan.strategy == "parallel":
            return await self._execute_parallel(session, plan)

        return await self._execute_maker_first(session, plan)

    def _simulate(self, plan: ExecutionPlan) -> ExecutionResult:
        """Simulate execution without placing real orders."""
        logger.info(
            "DRY RUN: Would execute %s strategy — Poly %s@%s + Kalshi %s@%s, margin=%s",
            plan.strategy,
            plan.poly_order.outcome,
            plan.poly_order.price,
            plan.kalshi_order.outcome,
            plan.kalshi_order.price,
            plan.expected_margin,
        )
        poly_result = OrderResult(
            order_id="dry-run-poly",
            status="filled",
            filled_price=plan.poly_order.price,
            filled_size=plan.poly_order.size,
            fees=Decimal("0"),  # Maker fee = 0
        )
        kalshi_result = OrderResult(
            order_id="dry-run-kalshi",
            status="filled",
            filled_price=plan.kalshi_order.price,
            filled_size=plan.kalshi_order.size,
            fees=plan.expected_fees,
        )
        pnl = plan.expected_margin - plan.expected_fees
        return ExecutionResult(
            status="dry_run",
            poly_result=poly_result,
            kalshi_result=kalshi_result,
            actual_pnl=pnl,
        )

    async def _execute_maker_first(self, session, plan: ExecutionPlan) -> ExecutionResult:
        """Maker-first: GTC on Polymarket, then IOC on Kalshi when filled."""
        from config import POLY_FILL_TIMEOUT, POLY_FILL_POLL_INTERVAL

        # Step 1: Place Polymarket GTC order
        poly_result, _ = await self.poly_client.place_order(plan.poly_order)
        if poly_result.status == "error" or poly_result.status == "rejected":
            return ExecutionResult(
                status="failed",
                poly_result=poly_result,
                error=f"Polymarket order failed: {poly_result.error}",
            )

        logger.info("Polymarket GTC order placed: %s", poly_result.order_id)

        # Step 2: Poll for fill
        filled = await self._wait_for_fill(poly_result.order_id, POLY_FILL_TIMEOUT, POLY_FILL_POLL_INTERVAL)
        if not filled:
            # Timeout — cancel the Polymarket order
            logger.warning("Polymarket order timed out, cancelling: %s", poly_result.order_id)
            await self.poly_client.cancel_order(poly_result.order_id)
            poly_result.status = "cancelled"
            return ExecutionResult(
                status="failed",
                poly_result=poly_result,
                error="Polymarket GTC order timed out",
            )

        poly_result.status = "filled"
        poly_result.filled_size = plan.poly_order.size
        poly_result.filled_price = plan.poly_order.price
        logger.info("Polymarket order filled: %s", poly_result.order_id)

        # Step 3: Place Kalshi IOC order
        kalshi_result, _ = await self.kalshi_client.place_order(session, plan.kalshi_order)
        if kalshi_result.status in ("error", "rejected", "cancelled"):
            # Kalshi leg failed — attempt rollback
            logger.error("Kalshi IOC failed: %s — attempting rollback", kalshi_result.error or kalshi_result.status)
            rollback_ok, rollback_err = await self._rollback(poly_result)
            return ExecutionResult(
                status="partial_fill",
                poly_result=poly_result,
                kalshi_result=kalshi_result,
                error=f"Kalshi leg failed: {kalshi_result.error or kalshi_result.status}. Rollback: {'success' if rollback_ok else rollback_err}",
            )

        # Both legs filled
        pnl = self._calculate_pnl(poly_result, kalshi_result)
        logger.info("Arbitrage executed successfully. P&L: %s", pnl)

        return ExecutionResult(
            status="success",
            poly_result=poly_result,
            kalshi_result=kalshi_result,
            actual_pnl=pnl,
        )

    async def _execute_parallel(self, session, plan: ExecutionPlan) -> ExecutionResult:
        """Parallel execution: both legs as FOK/IOC via asyncio.gather."""
        # Override order types for parallel execution
        plan.poly_order.order_type = "fok"
        plan.kalshi_order.order_type = "ioc"

        poly_task = self.poly_client.place_order(plan.poly_order)
        kalshi_task = self.kalshi_client.place_order(session, plan.kalshi_order)

        (poly_result, _), (kalshi_result, _) = await asyncio.gather(poly_task, kalshi_task)

        poly_ok = poly_result.status == "filled"
        kalshi_ok = kalshi_result.status == "filled"

        if poly_ok and kalshi_ok:
            pnl = self._calculate_pnl(poly_result, kalshi_result)
            return ExecutionResult(
                status="success",
                poly_result=poly_result,
                kalshi_result=kalshi_result,
                actual_pnl=pnl,
            )

        if poly_ok and not kalshi_ok:
            rollback_ok, rollback_err = await self._rollback(poly_result)
            return ExecutionResult(
                status="partial_fill",
                poly_result=poly_result,
                kalshi_result=kalshi_result,
                error=f"Kalshi leg failed. Rollback: {'success' if rollback_ok else rollback_err}",
            )

        if not poly_ok and kalshi_ok:
            # Rare: Kalshi filled but Poly didn't. Log the exposure.
            return ExecutionResult(
                status="partial_fill",
                poly_result=poly_result,
                kalshi_result=kalshi_result,
                error="Polymarket FOK failed but Kalshi filled — unhedged Kalshi position",
            )

        # Neither filled
        return ExecutionResult(
            status="failed",
            poly_result=poly_result,
            kalshi_result=kalshi_result,
            error="Neither leg filled",
        )

    async def _wait_for_fill(self, order_id: str, timeout: int, poll_interval: float) -> bool:
        """Poll Polymarket order status until filled or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data, err = await self.poly_client.get_order(order_id)
            if err:
                logger.warning("Error checking Poly order %s: %s", order_id, err)
                await asyncio.sleep(poll_interval)
                continue

            status = data.get("status", "").upper() if isinstance(data, dict) else ""
            if status in ("MATCHED", "FILLED"):
                return True
            if status in ("CANCELED", "CANCELLED", "EXPIRED"):
                return False

            await asyncio.sleep(poll_interval)

        return False

    async def _rollback(self, poly_result: OrderResult) -> tuple:
        """Attempt to unwind a Polymarket position.

        For Phase 2, we only attempt to cancel if still open.
        Full position unwinding (selling back) is deferred to Phase 4.

        Returns (success_bool, error) tuple.
        """
        try:
            ok, err = await self.poly_client.cancel_order(poly_result.order_id)
            if ok:
                logger.info("Rollback: cancelled Poly order %s", poly_result.order_id)
                return True, None
            else:
                logger.warning("Rollback failed for %s: %s", poly_result.order_id, err)
                return False, err
        except Exception as e:
            return False, f"Rollback exception: {e}"

    def _calculate_pnl(self, poly_result: OrderResult, kalshi_result: OrderResult) -> Decimal:
        """Calculate actual P&L from fill results."""
        payout = Decimal("1.00") * min(poly_result.filled_size, kalshi_result.filled_size)
        poly_cost = (poly_result.filled_price or Decimal("0")) * poly_result.filled_size
        kalshi_cost = (kalshi_result.filled_price or Decimal("0")) * kalshi_result.filled_size
        total_fees = poly_result.fees + kalshi_result.fees
        return payout - poly_cost - kalshi_cost - total_fees
