"""Tests that expose all four bugs in buggy_calculator.py.

These are the failing tests that would appear in a CI log and trigger
the auto-healing pipeline. Each test maps to one specific bug.
"""
from __future__ import annotations

import pytest

from demo.buggy_calculator import calculate_average_v1, calculate_average_v2


class TestCalculateAverageV1:
    """Exposes the two silent bugs in v1 (no crash — wrong output)."""

    def test_basic_average(self):
        # BUG 2 exposed: total == num is a no-op, total stays 0, returns 0/3 = 0.0
        assert calculate_average_v1([1, 2, 3]) == 2.0, (
            f"Expected 2.0 but got {calculate_average_v1([1, 2, 3])} — "
            "total == num is a comparison, not accumulation"
        )

    def test_single_element(self):
        assert calculate_average_v1([5]) == 5.0

    def test_floats(self):
        assert calculate_average_v1([1.0, 3.0]) == pytest.approx(2.0)

    def test_empty_list_returns_zero(self):
        # BUG 1 exposed: returns 1 instead of 0
        assert calculate_average_v1([]) == 0, (
            f"Expected 0 but got {calculate_average_v1([])} — "
            "return value for empty list is wrong"
        )


class TestCalculateAverageV2:
    """Exposes the two crash bugs in v2."""

    def test_basic_average(self):
        # BUG 3 exposed: IndexError: list index out of range
        assert calculate_average_v2([1, 2, 3]) == 2.0

    def test_single_element(self):
        assert calculate_average_v2([10]) == 10.0

    def test_empty_list_returns_zero(self):
        # BUG 4 exposed: ZeroDivisionError
        assert calculate_average_v2([]) == 0

    def test_negative_numbers(self):
        assert calculate_average_v2([-2, 0, 2]) == 0.0
