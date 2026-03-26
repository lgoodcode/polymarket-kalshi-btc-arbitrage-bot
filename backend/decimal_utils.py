"""Decimal conversion utilities for financial calculations.

Provides safe conversion between float/str/int and Decimal,
plus JSON serialization helpers.
"""
from decimal import Decimal


def to_decimal(value) -> Decimal:
    """Convert float/str/int to Decimal safely.

    Always converts via string to avoid float representation issues
    (e.g., Decimal(0.1) != Decimal("0.1")).
    """
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def to_float(value) -> float:
    """Convert Decimal to float for JSON serialization."""
    if isinstance(value, Decimal):
        return float(value)
    return float(value) if value is not None else 0.0


def decimal_to_json(obj):
    """Recursively convert Decimal values to float in a dict/list structure."""
    if isinstance(obj, dict):
        return {k: decimal_to_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_json(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    return obj
