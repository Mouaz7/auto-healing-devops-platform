"""Failing tests that expose all five advanced bugs.

Each test maps to exactly one bug. The error message and traceback that
pytest produces is the raw_log that would be sent to the auto-healing
pipeline — the pipeline must read it, generate a fix, and make these pass.
"""
from __future__ import annotations

import pytest

from demo.advanced_bugs import (
    Node,
    add_to_list,
    binary_search,
    fib_memo,
    fibonacci,
)


# ---------------------------------------------------------------------------
# Bug 1 — RecursionError: wrong base case in fibonacci
# ---------------------------------------------------------------------------

class TestFibonacci:
    def test_zero(self):
        # fibonacci(0) → RecursionError (base case n==1 misses n==0)
        assert fibonacci(0) == 0

    def test_one(self):
        assert fibonacci(1) == 1

    def test_five(self):
        assert fibonacci(5) == 5

    def test_ten(self):
        assert fibonacci(10) == 55

    def test_sequence(self):
        expected = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
        assert [fibonacci(i) for i in range(10)] == expected


# ---------------------------------------------------------------------------
# Bug 2 — AttributeError: missing return on recursive Node.find
# ---------------------------------------------------------------------------

class TestNodeFind:
    def _build_list(self) -> Node:
        """Build: 1 → 2 → 3 → 4 → 5"""
        return Node(1, Node(2, Node(3, Node(4, Node(5)))))

    def test_find_head(self):
        head = self._build_list()
        assert head.find(1).val == 1

    def test_find_middle(self):
        # find(3) reaches node 3 via recursion — missing return loses it
        head = self._build_list()
        result = head.find(3)
        assert result is not None, "find() returned None — missing return on recursive call"
        assert result.val == 3

    def test_find_tail(self):
        head = self._build_list()
        result = head.find(5)
        assert result is not None
        assert result.val == 5

    def test_find_missing_returns_none(self):
        head = self._build_list()
        assert head.find(99) is None


# ---------------------------------------------------------------------------
# Bug 3 — KeyError: reading memo before writing in fib_memo
# ---------------------------------------------------------------------------

class TestFibMemo:
    def test_base_zero(self):
        assert fib_memo(0) == 0

    def test_base_one(self):
        assert fib_memo(1) == 1

    def test_small(self):
        # KeyError: 2 on first call (memo is empty, n=2 not yet stored)
        assert fib_memo(2) == 1

    def test_medium(self):
        assert fib_memo(7) == 13

    def test_large(self):
        assert fib_memo(15) == 610


# ---------------------------------------------------------------------------
# Bug 4 — Infinite loop: binary search with low=mid / high=mid
# ---------------------------------------------------------------------------

class TestBinarySearch:
    def test_found_at_start(self):
        assert binary_search([1, 3, 5, 7, 9], 1) == 0

    def test_found_at_end(self):
        # arr[mid]=3 < target=9 → low=mid(=1) forever without mid+1
        assert binary_search([1, 3, 5, 7, 9], 9) == 4

    def test_found_in_middle(self):
        assert binary_search([1, 3, 5, 7, 9], 5) == 2

    def test_not_found(self):
        assert binary_search([1, 3, 5, 7, 9], 4) == -1

    def test_single_element_found(self):
        assert binary_search([42], 42) == 0

    def test_single_element_not_found(self):
        assert binary_search([42], 0) == -1


# ---------------------------------------------------------------------------
# Bug 5 — Mutable default argument: state leaks across calls
# ---------------------------------------------------------------------------

class TestAddToList:
    def test_independent_calls_return_separate_lists(self):
        # With mutable default [], both calls share the same list object.
        # Second call returns [10, 20] instead of [20].
        result1 = add_to_list(10)
        result2 = add_to_list(20)
        assert result1 == [10], f"First call should return [10], got {result1}"
        assert result2 == [20], (
            f"Second call should return [20] (independent list), got {result2}. "
            "Mutable default argument causes state leakage between calls."
        )

    def test_explicit_collection_not_modified_globally(self):
        my_list: list[int] = []
        add_to_list(1, my_list)
        add_to_list(2, my_list)
        assert my_list == [1, 2]

    def test_fresh_list_each_call(self):
        calls = [add_to_list(i) for i in range(5)]
        for i, result in enumerate(calls):
            assert result == [i], (
                f"Call {i} should return [{i}], got {result} — "
                "mutable default is shared across all calls"
            )
