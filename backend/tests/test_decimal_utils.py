"""Tests for Decimal conversion utilities."""
import sys
import os
import pytest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from decimal_utils import to_decimal, to_float, decimal_to_json


class TestToDecimal:
    def test_from_float(self):
        assert to_decimal(0.5) == Decimal("0.5")

    def test_from_string(self):
        assert to_decimal("0.47") == Decimal("0.47")

    def test_from_int(self):
        assert to_decimal(100) == Decimal("100")

    def test_from_decimal(self):
        d = Decimal("0.35")
        assert to_decimal(d) is d  # pass-through

    def test_none_returns_zero(self):
        assert to_decimal(None) == Decimal("0")

    def test_negative(self):
        assert to_decimal(-0.5) == Decimal("-0.5")

    def test_zero(self):
        assert to_decimal(0) == Decimal("0")

    def test_large_value(self):
        assert to_decimal(100000) == Decimal("100000")


class TestToFloat:
    def test_from_decimal(self):
        assert to_float(Decimal("0.55")) == 0.55

    def test_from_int(self):
        assert to_float(42) == 42.0

    def test_none_returns_zero(self):
        assert to_float(None) == 0.0

    def test_from_float(self):
        assert to_float(0.5) == 0.5


class TestDecimalToJson:
    def test_flat_dict(self):
        result = decimal_to_json({"price": Decimal("0.55"), "name": "test"})
        assert result == {"price": 0.55, "name": "test"}

    def test_nested_dict(self):
        result = decimal_to_json({
            "outer": {"inner": Decimal("0.42")},
        })
        assert result == {"outer": {"inner": 0.42}}

    def test_list_of_decimals(self):
        result = decimal_to_json([Decimal("1"), Decimal("2"), Decimal("3")])
        assert result == [1.0, 2.0, 3.0]

    def test_mixed_types(self):
        result = decimal_to_json({
            "price": Decimal("0.55"),
            "name": "test",
            "count": 10,
            "items": [Decimal("0.1"), "hello", 42],
        })
        assert result["price"] == 0.55
        assert result["name"] == "test"
        assert result["count"] == 10
        assert result["items"] == [0.1, "hello", 42]

    def test_empty_containers(self):
        assert decimal_to_json({}) == {}
        assert decimal_to_json([]) == []

    def test_non_decimal_passthrough(self):
        assert decimal_to_json("hello") == "hello"
        assert decimal_to_json(42) == 42
        assert decimal_to_json(None) is None

    def test_deeply_nested(self):
        result = decimal_to_json({"a": [{"b": Decimal("0.99")}]})
        assert result == {"a": [{"b": 0.99}]}
