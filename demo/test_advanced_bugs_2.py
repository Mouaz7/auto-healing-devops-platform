"""Failing tests that expose all five bugs in advanced_bugs_2.py."""
from __future__ import annotations

import pytest

from demo.advanced_bugs_2 import (
    calculate_grade,
    find_first_zero,
    flatten,
    graph_bfs,
    remove_low_scores,
)


# ---------------------------------------------------------------------------
# Bug 1 — BFS infinite loop on cyclic graph (timeout in pytest)
# ---------------------------------------------------------------------------

class TestGraphBFS:
    def test_linear_graph(self):
        g = {"A": ["B"], "B": ["C"], "C": []}
        assert graph_bfs(g, "A") == ["A", "B", "C"]

    def test_single_node(self):
        assert graph_bfs({"X": []}, "X") == ["X"]

    def test_cyclic_graph_does_not_loop(self):
        # A → B → A (cycle) — without visited set this hangs forever
        g = {"A": ["B"], "B": ["A"]}
        result = graph_bfs(g, "A")
        assert set(result) == {"A", "B"}, (
            "BFS revisited nodes in a cycle — missing visited set"
        )

    def test_diamond_graph(self):
        # A → B, A → C, B → D, C → D (diamond, D reachable twice)
        g = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        result = graph_bfs(g, "A")
        assert result.count("D") == 1, "D should only appear once (visited set missing)"
        assert set(result) == {"A", "B", "C", "D"}


# ---------------------------------------------------------------------------
# Bug 2 — UnboundLocalError for out-of-range scores
# ---------------------------------------------------------------------------

class TestCalculateGrade:
    def test_a_grade(self):
        assert calculate_grade(95) == "A"

    def test_f_grade(self):
        assert calculate_grade(55) == "F"

    def test_boundary_90(self):
        assert calculate_grade(90) == "A"

    def test_out_of_range_high(self):
        # score=101 → no branch assigns grade → UnboundLocalError
        result = calculate_grade(101)
        assert result == "INVALID", f"Expected 'INVALID' for score=101, got {result!r}"

    def test_negative_score(self):
        # score=-1 → no branch assigns grade → UnboundLocalError
        result = calculate_grade(-1)
        assert result == "INVALID", f"Expected 'INVALID' for score=-1, got {result!r}"


# ---------------------------------------------------------------------------
# Bug 3 — RuntimeError: dict changed size during iteration
# ---------------------------------------------------------------------------

class TestRemoveLowScores:
    def test_remove_below_threshold(self):
        scores = {"Alice": 90, "Bob": 40, "Carol": 75, "Dave": 30}
        result = remove_low_scores(scores, 60)
        assert result == {"Alice": 90, "Carol": 75}

    def test_remove_none(self):
        scores = {"Alice": 90, "Bob": 80}
        result = remove_low_scores(scores, 50)
        assert result == {"Alice": 90, "Bob": 80}

    def test_remove_all(self):
        scores = {"Alice": 10, "Bob": 20}
        result = remove_low_scores(scores, 50)
        assert result == {}

    def test_multiple_removals(self):
        scores = {str(i): i for i in range(10)}
        result = remove_low_scores(scores, 5)
        assert all(v >= 5 for v in result.values())


# ---------------------------------------------------------------------------
# Bug 4 — TypeError: NoneType not iterable (missing return result)
# ---------------------------------------------------------------------------

class TestFlatten:
    def test_already_flat(self):
        assert flatten([1, 2, 3]) == [1, 2, 3]

    def test_one_level(self):
        assert flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]

    def test_deeply_nested(self):
        # Recursive call discards result → TypeError: NoneType not iterable
        assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]

    def test_mixed(self):
        assert flatten([1, [2, 3], 4, [5, [6]]]) == [1, 2, 3, 4, 5, 6]

    def test_empty(self):
        assert flatten([]) == []

    def test_nested_empty(self):
        assert flatten([[], [1, []], 2]) == [1, 2]


# ---------------------------------------------------------------------------
# Bug 5 — `is` vs `==` wrong for non-interned integers
# ---------------------------------------------------------------------------

class TestFindFirstZero:
    def test_zero_at_start(self):
        assert find_first_zero([0, 1, 2]) == 0

    def test_zero_in_middle(self):
        assert find_first_zero([1, 2, 0, 3]) == 2

    def test_no_zero(self):
        assert find_first_zero([1, 2, 3]) == -1

    def test_runtime_zero_not_interned(self):
        # int('0') creates a zero that may not be the same object as literal 0
        # `is` fails here; `==` would not.
        z = int("0")
        result = find_first_zero([1, 2, z, 3])
        assert result == 2, (
            f"Expected index 2 for runtime-created zero, got {result}. "
            "Use == not `is` for value comparison."
        )

    def test_large_integer_identity(self):
        # Integers outside CPython's intern range (-5..256) are not singletons.
        # `is 0` works by accident for literal 0 (interned) but is semantically wrong.
        values = [1000, 2000, 0, 3000]
        assert find_first_zero(values) == 2
