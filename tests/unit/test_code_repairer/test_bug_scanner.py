"""Unit tests for BugPatternScanner — all 18 patterns."""
from __future__ import annotations

import pytest

from src.llm_mcp.bug_scanner import BugPatternScanner, ScanResult


def scan(source: str) -> ScanResult:
    return BugPatternScanner.scan(source)


def patterns(source: str) -> list[str]:
    return [f.pattern for f in scan(source).findings]


# ---------------------------------------------------------------------------
# Pattern 1 — comparison_as_assignment
# ---------------------------------------------------------------------------

class TestComparisonAsAssignment:
    def test_detects_total_equals_num(self) -> None:
        code = (
            "def avg(nums):\n"
            "    total = 0\n"
            "    for num in nums:\n"
            "        total == num\n"
            "    return total\n"
        )
        assert "comparison_as_assignment" in patterns(code)

    def test_clean_accumulation_no_hit(self) -> None:
        code = (
            "def avg(nums):\n"
            "    total = 0\n"
            "    for num in nums:\n"
            "        total += num\n"
            "    return total\n"
        )
        assert "comparison_as_assignment" not in patterns(code)

    def test_to_prompt_block_lists_fix(self) -> None:
        code = (
            "def s(x):\n"
            "    t = 0\n"
            "    for n in x:\n"
            "        t == n\n"
            "    return t\n"
        )
        result = scan(code)
        block = result.to_prompt_block()
        assert "COMPARISON_AS_ASSIGNMENT" in block
        assert "+=" in block


# ---------------------------------------------------------------------------
# Pattern 2 — wrong_edge_return
# ---------------------------------------------------------------------------

class TestWrongEdgeReturn:
    def test_detects_return_one(self) -> None:
        code = (
            "def avg(nums):\n"
            "    if not nums:\n"
            "        return 1\n"
            "    return sum(nums) / len(nums)\n"
        )
        assert "wrong_edge_return" in patterns(code)

    def test_return_zero_is_fine(self) -> None:
        code = (
            "def avg(nums):\n"
            "    if not nums:\n"
            "        return 0\n"
            "    return sum(nums) / len(nums)\n"
        )
        assert "wrong_edge_return" not in patterns(code)

    def test_return_none_is_fine(self) -> None:
        code = (
            "def first(lst):\n"
            "    if not lst:\n"
            "        return None\n"
            "    return lst[0]\n"
        )
        assert "wrong_edge_return" not in patterns(code)

    def test_return_minus_one_is_fine(self) -> None:
        code = (
            "def find(lst):\n"
            "    if not lst:\n"
            "        return -1\n"
            "    return lst.index(0)\n"
        )
        assert "wrong_edge_return" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 3 — wrong_arithmetic_op
# ---------------------------------------------------------------------------

class TestWrongArithmeticOp:
    def test_detects_subtract_len(self) -> None:
        code = (
            "def calculate_average(numbers):\n"
            "    total = sum(numbers)\n"
            "    return total - len(numbers)\n"
        )
        assert "wrong_arithmetic_op" in patterns(code)

    def test_divide_is_correct(self) -> None:
        code = (
            "def calculate_average(numbers):\n"
            "    return sum(numbers) / len(numbers)\n"
        )
        assert "wrong_arithmetic_op" not in patterns(code)

    def test_non_float_context_ignored(self) -> None:
        code = (
            "def process(items):\n"
            "    return sum(items) - len(items)\n"
        )
        assert "wrong_arithmetic_op" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 4 — off_by_one_range
# ---------------------------------------------------------------------------

class TestOffByOneRange:
    def test_range_len_plus_one(self) -> None:
        code = (
            "def iterate(nums):\n"
            "    for i in range(len(nums) + 1):\n"
            "        print(nums[i])\n"
        )
        assert "off_by_one_range" in patterns(code)

    def test_range_len_correct(self) -> None:
        code = (
            "def iterate(nums):\n"
            "    for i in range(len(nums)):\n"
            "        print(nums[i])\n"
        )
        assert "off_by_one_range" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 5 — mutable_default_arg
# ---------------------------------------------------------------------------

class TestMutableDefaultArg:
    def test_detects_list_default(self) -> None:
        code = "def f(x, items=[]):\n    items.append(x)\n    return items\n"
        assert "mutable_default_arg" in patterns(code)

    def test_detects_dict_default(self) -> None:
        code = "def f(x, cache={}):\n    return cache.get(x)\n"
        assert "mutable_default_arg" in patterns(code)

    def test_none_default_is_fine(self) -> None:
        code = "def f(x, items=None):\n    if items is None: items = []\n    return items\n"
        assert "mutable_default_arg" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 6 — missing_return
# ---------------------------------------------------------------------------

class TestMissingReturn:
    def test_detects_branch_fallthrough(self) -> None:
        # last stmt is an assignment, not a return/loop — falls through to None
        code = (
            "def process(x):\n"
            "    if x > 0:\n"
            "        return x\n"
            "    y = -x\n"
        )
        assert "missing_return" in patterns(code)

    def test_function_with_return_is_fine(self) -> None:
        code = (
            "def process(x):\n"
            "    if x > 0:\n"
            "        return x\n"
            "    return -x\n"
        )
        assert "missing_return" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 7 — is_literal_comparison
# ---------------------------------------------------------------------------

class TestIsLiteralComparison:
    def test_detects_is_integer(self) -> None:
        code = "if x is 0:\n    pass\n"
        assert "is_literal_comparison" in patterns(code)

    def test_detects_is_string(self) -> None:
        code = "if name is 'hello':\n    pass\n"
        assert "is_literal_comparison" in patterns(code)

    def test_is_none_is_fine(self) -> None:
        code = "if x is None:\n    pass\n"
        assert "is_literal_comparison" not in patterns(code)

    def test_is_true_is_fine(self) -> None:
        code = "if x is True:\n    pass\n"
        assert "is_literal_comparison" not in patterns(code)

    def test_equality_is_fine(self) -> None:
        code = "if x == 0:\n    pass\n"
        assert "is_literal_comparison" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 8 — floor_div_float_context
# ---------------------------------------------------------------------------

class TestFloorDivFloatContext:
    def test_detects_double_slash_in_average(self) -> None:
        code = (
            "def average(nums):\n"
            "    return sum(nums) // len(nums)\n"
        )
        assert "floor_div_float_context" in patterns(code)

    def test_single_div_is_fine(self) -> None:
        code = (
            "def average(nums):\n"
            "    return sum(nums) / len(nums)\n"
        )
        assert "floor_div_float_context" not in patterns(code)

    def test_floor_div_outside_float_context_ignored(self) -> None:
        code = (
            "def index_of(items, n):\n"
            "    return n // 2\n"
        )
        assert "floor_div_float_context" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 10 — divide_without_guard
# ---------------------------------------------------------------------------

class TestDivideWithoutGuard:
    def test_detects_sum_div_len_no_guard(self) -> None:
        code = (
            "def avg(nums):\n"
            "    return sum(nums) / len(nums)\n"
        )
        assert "divide_without_guard" in patterns(code)

    def test_with_guard_no_hit(self) -> None:
        code = (
            "def avg(nums):\n"
            "    if not nums:\n"
            "        return 0\n"
            "    return sum(nums) / len(nums)\n"
        )
        assert "divide_without_guard" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 11 — recursive_call_not_returned
# ---------------------------------------------------------------------------

class TestRecursiveCallNotReturned:
    def test_detects_missing_return_on_recursive_call(self) -> None:
        code = (
            "class Node:\n"
            "    def find(self, t):\n"
            "        if self.val == t: return self\n"
            "        if self.next: self.next.find(t)\n"
            "        return None\n"
        )
        assert "recursive_call_not_returned" in patterns(code)

    def test_returned_recursive_call_is_fine(self) -> None:
        code = (
            "class Node:\n"
            "    def find(self, t):\n"
            "        if self.val == t: return self\n"
            "        if self.next: return self.next.find(t)\n"
            "        return None\n"
        )
        assert "recursive_call_not_returned" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 12 — wrong_range_direction
# ---------------------------------------------------------------------------

class TestWrongRangeDirection:
    def test_detects_constant_range_backwards(self) -> None:
        # Detection requires constant integers — range(10, 0) produces empty seq
        code = (
            "def countdown():\n"
            "    for i in range(10, 0):\n"
            "        print(i)\n"
        )
        assert "wrong_range_direction" in patterns(code)

    def test_range_with_step_is_fine(self) -> None:
        code = (
            "def countdown():\n"
            "    for i in range(10, 0, -1):\n"
            "        print(i)\n"
        )
        assert "wrong_range_direction" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 13 — bare_except
# ---------------------------------------------------------------------------

class TestBareExcept:
    def test_detects_bare_except(self) -> None:
        code = (
            "try:\n"
            "    x = int(s)\n"
            "except:\n"
            "    x = 0\n"
        )
        assert "bare_except" in patterns(code)

    def test_typed_except_is_fine(self) -> None:
        code = (
            "try:\n"
            "    x = int(s)\n"
            "except ValueError:\n"
            "    x = 0\n"
        )
        assert "bare_except" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 14 — return_in_finally
# ---------------------------------------------------------------------------

class TestReturnInFinally:
    def test_detects_return_in_finally(self) -> None:
        code = (
            "def f():\n"
            "    try:\n"
            "        return 1\n"
            "    finally:\n"
            "        return 0\n"
        )
        assert "return_in_finally" in patterns(code)

    def test_return_only_in_try_is_fine(self) -> None:
        code = (
            "def f():\n"
            "    try:\n"
            "        return 1\n"
            "    finally:\n"
            "        print('done')\n"
        )
        assert "return_in_finally" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 16 — str_method_not_assigned
# ---------------------------------------------------------------------------

class TestStrMethodNotAssigned:
    def test_detects_replace_result_discarded(self) -> None:
        code = (
            "s = 'hello world'\n"
            "s.replace('world', 'python')\n"
            "print(s)\n"
        )
        assert "str_method_not_assigned" in patterns(code)

    def test_assigned_replace_is_fine(self) -> None:
        code = (
            "s = 'hello world'\n"
            "s = s.replace('world', 'python')\n"
            "print(s)\n"
        )
        assert "str_method_not_assigned" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 17 — shadow_builtin
# ---------------------------------------------------------------------------

class TestShadowBuiltin:
    def test_detects_list_assignment(self) -> None:
        code = "list = [1, 2, 3]\n"
        assert "shadow_builtin" in patterns(code)

    def test_detects_dict_assignment(self) -> None:
        code = "dict = {'a': 1}\n"
        assert "shadow_builtin" in patterns(code)

    def test_normal_name_is_fine(self) -> None:
        code = "my_list = [1, 2, 3]\n"
        assert "shadow_builtin" not in patterns(code)


# ---------------------------------------------------------------------------
# ScanResult helpers
# ---------------------------------------------------------------------------

class TestScanResult:
    def test_empty_result_has_no_bugs(self) -> None:
        result = scan("x = 1\n")
        assert not result.has_bugs
        assert result.to_prompt_block() == ""

    def test_syntax_error_source_returns_parse_error(self) -> None:
        result = scan("def f(\n")
        assert result.parse_error != ""
        assert not result.has_bugs

    def test_prompt_block_includes_all_findings(self) -> None:
        code = (
            "def avg(nums):\n"
            "    total = 0\n"
            "    for n in nums:\n"
            "        total == n\n"
            "    if not nums:\n"
            "        return 1\n"
        )
        block = scan(code).to_prompt_block()
        assert "STATIC BUG SCAN" in block
        assert "COMPARISON_AS_ASSIGNMENT" in block
        assert "WRONG_EDGE_RETURN" in block

    def test_multiple_bugs_all_numbered(self) -> None:
        code = (
            "def avg(nums):\n"
            "    total = 0\n"
            "    for n in nums:\n"
            "        total == n\n"
            "    return total - len(nums)\n"
        )
        block = scan(code).to_prompt_block()
        assert "[1]" in block
        assert "[2]" in block
