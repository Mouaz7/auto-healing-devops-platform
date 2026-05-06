"""Failing tests that expose all ten bugs in advanced_bugs_3.py."""
from __future__ import annotations

import pytest

from demo.advanced_bugs_3 import (
    build_config,
    calculate_stats,
    compute_product,
    find_max,
    is_even,
    load_data,
    normalize_average,
    point_distance,
    Container,
)


# ---------------------------------------------------------------------------
# Bug 1+2 — wrong accumulator init + loop overwrites
# ---------------------------------------------------------------------------

class TestCalculateStats:
    def test_sum_is_correct(self):
        result = calculate_stats([1.0, 2.0, 3.0])
        assert result["sum"] == 6.0, (
            f"Expected sum=6.0 but got {result['sum']}. "
            "Check: total = 0 and total += n"
        )

    def test_average_is_correct(self):
        result = calculate_stats([10.0, 20.0, 30.0])
        assert result["average"] == 20.0, (
            f"Expected average=20.0 but got {result['average']}"
        )

    def test_single_element(self):
        result = calculate_stats([5.0])
        assert result["sum"] == 5.0

    def test_empty_returns_zeros(self):
        result = calculate_stats([])
        assert result == {"sum": 0, "count": 0, "average": 0.0}


# ---------------------------------------------------------------------------
# Bug 3 — duplicate dict key
# ---------------------------------------------------------------------------

class TestBuildConfig:
    def test_host_is_unique(self):
        config = build_config()
        # A dict can only have one value per key — if 'host' is duplicated
        # in the literal Python silently picks the last one.
        # The test documents that 'localhost' must be accessible:
        assert config["host"] == "localhost", (
            f"Expected 'localhost' but got {config['host']!r}. "
            "Duplicate dict key 'host' — second value overwrites first."
        )

    def test_all_keys_present(self):
        config = build_config()
        assert set(config) == {"host", "port", "database"}


# ---------------------------------------------------------------------------
# Bug 4 — wrong product sentinel
# ---------------------------------------------------------------------------

class TestComputeProduct:
    def test_small_list(self):
        assert compute_product([1, 2, 3, 4]) == 24, (
            "Expected 24. Hint: product = 0 always gives 0."
        )

    def test_single_element(self):
        assert compute_product([7]) == 7

    def test_ones(self):
        assert compute_product([1, 1, 1]) == 1


# ---------------------------------------------------------------------------
# Bug 5 — wrong max sentinel
# ---------------------------------------------------------------------------

class TestFindMax:
    def test_positive_numbers(self):
        assert find_max([3.0, 1.0, 4.0, 1.0, 5.0]) == 5.0

    def test_all_negative(self):
        result = find_max([-3.0, -1.0, -4.0])
        assert result == -1.0, (
            f"Expected -1.0 but got {result}. "
            "max_val = 0 fails for all-negative lists."
        )

    def test_mix_positive_negative(self):
        assert find_max([-5.0, 3.0, -1.0]) == 3.0


# ---------------------------------------------------------------------------
# Bug 6 — augmented subtract
# ---------------------------------------------------------------------------

class TestNormalizeAverage:
    def test_basic_average(self):
        result = normalize_average([1.0, 2.0, 3.0])
        assert result == pytest.approx(2.0), (
            f"Expected 2.0 but got {result}. Hint: use += not -=."
        )

    def test_single_value(self):
        assert normalize_average([10.0]) == pytest.approx(10.0)

    def test_empty(self):
        assert normalize_average([]) == 0.0


# ---------------------------------------------------------------------------
# Bug 7 — == None
# ---------------------------------------------------------------------------

class TestPointDistance:
    def test_basic_distance(self):
        d = point_distance((0.0, 0.0), (3.0, 4.0))
        assert d == pytest.approx(5.0)

    def test_none_first_arg(self):
        assert point_distance(None, (1.0, 1.0)) == 0.0

    def test_both_none(self):
        assert point_distance(None, None) == 0.0

    def test_same_point(self):
        assert point_distance((1.0, 1.0), (1.0, 1.0)) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Bug 8 — forgot self.
# ---------------------------------------------------------------------------

class TestContainer:
    def test_info_shows_name(self):
        c = Container("box", 10)
        assert "box" in c.info(), (
            "Container.info() should include the name. "
            "Check: self.name = name in __init__."
        )

    def test_info_shows_capacity(self):
        c = Container("bin", 5)
        assert "5" in c.info()

    def test_items_starts_empty(self):
        c = Container("tray", 3)
        assert c.items == []


# ---------------------------------------------------------------------------
# Bug 9 — exception swallowed
# ---------------------------------------------------------------------------

class TestLoadData:
    def test_valid_integer(self):
        assert load_data("42") == 42

    def test_invalid_string_returns_minus_one(self):
        result = load_data("not_a_number")
        assert result == -1, (
            f"Expected -1 for invalid input but got {result!r}. "
            "The except block must set a fallback value, not just `pass`."
        )

    def test_float_string_returns_minus_one(self):
        result = load_data("3.14")
        assert result == -1


# ---------------------------------------------------------------------------
# Bug 10 — redundant bool comparison
# ---------------------------------------------------------------------------

class TestIsEven:
    def test_even_number(self):
        assert is_even(4) is True

    def test_odd_number(self):
        assert is_even(3) is False

    def test_zero(self):
        assert is_even(0) is True

    def test_negative_even(self):
        assert is_even(-6) is True
