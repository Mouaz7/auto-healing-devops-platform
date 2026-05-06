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


# ---------------------------------------------------------------------------
# Pattern 19 — wrong_accumulator_init
# ---------------------------------------------------------------------------

class TestWrongAccumulatorInit:
    def test_detects_total_equals_one(self) -> None:
        code = (
            "def avg(nums):\n"
            "    total = 1\n"
            "    for n in nums:\n"
            "        total += n\n"
            "    return total / len(nums)\n"
        )
        assert "wrong_accumulator_init" in patterns(code)

    def test_detects_with_comparison_in_loop(self) -> None:
        # total = 1 and loop has total == n (double bug case)
        code = (
            "def avg(nums):\n"
            "    total = 1\n"
            "    for n in nums:\n"
            "        total == n\n"
            "    return total\n"
        )
        assert "wrong_accumulator_init" in patterns(code)

    def test_total_zero_is_fine(self) -> None:
        code = (
            "def avg(nums):\n"
            "    total = 0\n"
            "    for n in nums:\n"
            "        total += n\n"
            "    return total / len(nums)\n"
        )
        assert "wrong_accumulator_init" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 20 — loop_overwrites_accumulator
# ---------------------------------------------------------------------------

class TestLoopOverwritesAccumulator:
    def test_detects_total_equals_loop_var(self) -> None:
        code = (
            "def s(nums):\n"
            "    total = 0\n"
            "    for num in nums:\n"
            "        total = num\n"
            "    return total\n"
        )
        assert "loop_overwrites_accumulator" in patterns(code)

    def test_augmented_assign_is_fine(self) -> None:
        code = (
            "def s(nums):\n"
            "    total = 0\n"
            "    for num in nums:\n"
            "        total += num\n"
            "    return total\n"
        )
        assert "loop_overwrites_accumulator" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 21 — none_equality_check
# ---------------------------------------------------------------------------

class TestNoneEqualityCheck:
    def test_detects_eq_none(self) -> None:
        code = "if x == None:\n    pass\n"
        assert "none_equality_check" in patterns(code)

    def test_detects_neq_none(self) -> None:
        code = "if x != None:\n    pass\n"
        assert "none_equality_check" in patterns(code)

    def test_is_none_is_fine(self) -> None:
        code = "if x is None:\n    pass\n"
        assert "none_equality_check" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 22 — type_not_isinstance
# ---------------------------------------------------------------------------

class TestTypeNotIsinstance:
    def test_detects_type_eq(self) -> None:
        code = "if type(x) == list:\n    pass\n"
        assert "type_not_isinstance" in patterns(code)

    def test_isinstance_is_fine(self) -> None:
        code = "if isinstance(x, list):\n    pass\n"
        assert "type_not_isinstance" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 23 — exception_swallowed
# ---------------------------------------------------------------------------

class TestExceptionSwallowed:
    def test_detects_except_pass(self) -> None:
        code = (
            "try:\n"
            "    x = int(s)\n"
            "except ValueError:\n"
            "    pass\n"
        )
        assert "exception_swallowed" in patterns(code)

    def test_except_with_log_is_fine(self) -> None:
        code = (
            "try:\n"
            "    x = int(s)\n"
            "except ValueError:\n"
            "    x = -1\n"
        )
        assert "exception_swallowed" not in patterns(code)

    def test_bare_except_not_double_flagged(self) -> None:
        # bare_except fires; exception_swallowed should NOT also fire (no type)
        code = (
            "try:\n"
            "    x = 1\n"
            "except:\n"
            "    pass\n"
        )
        hits = patterns(code)
        assert "bare_except" in hits
        assert "exception_swallowed" not in hits


# ---------------------------------------------------------------------------
# Pattern 24 — unreachable_code_after_return
# ---------------------------------------------------------------------------

class TestUnreachableAfterReturn:
    def test_detects_statement_after_return(self) -> None:
        code = (
            "def f(x):\n"
            "    return x\n"
            "    y = x + 1\n"
            "    return y\n"
        )
        assert "unreachable_code_after_return" in patterns(code)

    def test_no_unreachable_in_branches(self) -> None:
        code = (
            "def f(x):\n"
            "    if x > 0:\n"
            "        return x\n"
            "    return -x\n"
        )
        assert "unreachable_code_after_return" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 25 — sorted_result_discarded
# ---------------------------------------------------------------------------

class TestSortedResultDiscarded:
    def test_detects_sorted_standalone(self) -> None:
        code = "sorted(my_list)\n"
        assert "sorted_result_discarded" in patterns(code)

    def test_assigned_sorted_is_fine(self) -> None:
        code = "my_list = sorted(my_list)\n"
        assert "sorted_result_discarded" not in patterns(code)

    def test_sort_method_is_fine(self) -> None:
        code = "my_list.sort()\n"
        assert "sorted_result_discarded" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 26 — redundant_bool_comparison
# ---------------------------------------------------------------------------

class TestRedundantBoolComparison:
    def test_detects_eq_true(self) -> None:
        code = "if x == True:\n    pass\n"
        assert "redundant_bool_comparison" in patterns(code)

    def test_detects_eq_false(self) -> None:
        code = "if x == False:\n    pass\n"
        assert "redundant_bool_comparison" in patterns(code)

    def test_is_true_not_flagged(self) -> None:
        code = "if x is True:\n    pass\n"
        assert "redundant_bool_comparison" not in patterns(code)

    def test_bare_if_is_fine(self) -> None:
        code = "if x:\n    pass\n"
        assert "redundant_bool_comparison" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 27 — augmented_subtract_in_sum
# ---------------------------------------------------------------------------

class TestAugmentedSubtractInSum:
    def test_detects_minus_equals_in_average(self) -> None:
        code = (
            "def average(nums):\n"
            "    total = 0.0\n"
            "    for n in nums:\n"
            "        total -= n\n"
            "    return total / len(nums)\n"
        )
        assert "augmented_subtract_in_sum" in patterns(code)

    def test_plus_equals_is_fine(self) -> None:
        code = (
            "def average(nums):\n"
            "    total = 0.0\n"
            "    for n in nums:\n"
            "        total += n\n"
            "    return total / len(nums)\n"
        )
        assert "augmented_subtract_in_sum" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 28 — forgot_self_dot
# ---------------------------------------------------------------------------

class TestForgotSelfDot:
    def test_detects_name_eq_name_in_init(self) -> None:
        code = (
            "class Foo:\n"
            "    def __init__(self, name):\n"
            "        name = name\n"
        )
        assert "forgot_self_dot" in patterns(code)

    def test_self_dot_is_fine(self) -> None:
        code = (
            "class Foo:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
        )
        assert "forgot_self_dot" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 29 — duplicate_dict_key
# ---------------------------------------------------------------------------

class TestDuplicateDictKey:
    def test_detects_duplicate_string_key(self) -> None:
        code = "d = {'a': 1, 'b': 2, 'a': 3}\n"
        assert "duplicate_dict_key" in patterns(code)

    def test_unique_keys_is_fine(self) -> None:
        code = "d = {'a': 1, 'b': 2, 'c': 3}\n"
        assert "duplicate_dict_key" not in patterns(code)

    def test_detects_duplicate_integer_key(self) -> None:
        code = "d = {1: 'one', 2: 'two', 1: 'ONE'}\n"
        assert "duplicate_dict_key" in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 30 — wrong_product_sentinel
# ---------------------------------------------------------------------------

class TestWrongProductSentinel:
    def test_detects_product_equals_zero(self) -> None:
        code = (
            "def multiply(nums):\n"
            "    product = 0\n"
            "    for n in nums:\n"
            "        product *= n\n"
            "    return product\n"
        )
        assert "wrong_product_sentinel" in patterns(code)

    def test_product_one_is_fine(self) -> None:
        code = (
            "def multiply(nums):\n"
            "    product = 1\n"
            "    for n in nums:\n"
            "        product *= n\n"
            "    return product\n"
        )
        assert "wrong_product_sentinel" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 31 — float_exact_equality
# ---------------------------------------------------------------------------

class TestFloatExactEquality:
    def test_detects_eq_float_literal(self) -> None:
        code = "if result == 0.1:\n    pass\n"
        assert "float_exact_equality" in patterns(code)

    def test_eq_zero_float_is_fine(self) -> None:
        # 0.0 has exact float representation
        code = "if x == 0.0:\n    pass\n"
        assert "float_exact_equality" not in patterns(code)

    def test_math_isclose_suggestion_in_block(self) -> None:
        code = "if x == 0.3:\n    pass\n"
        block = scan(code).to_prompt_block()
        assert "isclose" in block or "1e-9" in block


# ---------------------------------------------------------------------------
# Pattern 33 — inconsistent_return
# ---------------------------------------------------------------------------

class TestInconsistentReturn:
    def test_detects_mixed_returns(self) -> None:
        code = (
            "def find(lst, x):\n"
            "    for i, v in enumerate(lst):\n"
            "        if v == x:\n"
            "            return i\n"
            "    return\n"  # bare return — returns None
        )
        assert "inconsistent_return" in patterns(code)

    def test_all_return_value_is_fine(self) -> None:
        code = (
            "def find(lst, x):\n"
            "    for i, v in enumerate(lst):\n"
            "        if v == x:\n"
            "            return i\n"
            "    return -1\n"
        )
        assert "inconsistent_return" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 34 — star_import
# ---------------------------------------------------------------------------

class TestStarImport:
    def test_detects_from_star(self) -> None:
        code = "from os import *\n"
        assert "star_import" in patterns(code)

    def test_named_import_is_fine(self) -> None:
        code = "from os import path, getcwd\n"
        assert "star_import" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 35 — import_in_loop
# ---------------------------------------------------------------------------

class TestImportInLoop:
    def test_detects_import_in_for(self) -> None:
        code = "for i in range(3):\n    import os\n    print(i)\n"
        assert "import_in_loop" in patterns(code)

    def test_top_level_import_fine(self) -> None:
        code = "import os\nfor i in range(3):\n    print(os.getcwd())\n"
        assert "import_in_loop" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 36 — list_multiply_shared_refs
# ---------------------------------------------------------------------------

class TestListMultiplySharedRefs:
    def test_detects_list_of_lists_multiply(self) -> None:
        code = "grid = [[0]] * 3\n"
        assert "list_multiply_shared_refs" in patterns(code)

    def test_list_of_ints_is_fine(self) -> None:
        code = "zeros = [0] * 5\n"
        assert "list_multiply_shared_refs" not in patterns(code)

    def test_list_comp_is_fine(self) -> None:
        code = "grid = [[] for _ in range(3)]\n"
        assert "list_multiply_shared_refs" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 37 — missing_super_init
# ---------------------------------------------------------------------------

class TestMissingSuperInit:
    def test_detects_subclass_without_super(self) -> None:
        code = (
            "class Dog(Animal):\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
        )
        assert "missing_super_init" in patterns(code)

    def test_with_super_call_is_fine(self) -> None:
        code = (
            "class Dog(Animal):\n"
            "    def __init__(self, name):\n"
            "        super().__init__()\n"
            "        self.name = name\n"
        )
        assert "missing_super_init" not in patterns(code)

    def test_no_bases_is_fine(self) -> None:
        code = (
            "class Dog:\n"
            "    def __init__(self):\n"
            "        self.name = 'Rex'\n"
        )
        assert "missing_super_init" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 38 — class_mutable_attribute
# ---------------------------------------------------------------------------

class TestClassMutableAttribute:
    def test_detects_class_level_list(self) -> None:
        code = "class Cart:\n    items = []\n"
        assert "class_mutable_attribute" in patterns(code)

    def test_detects_class_level_dict(self) -> None:
        code = "class Cache:\n    store = {}\n"
        assert "class_mutable_attribute" in patterns(code)

    def test_instance_attr_in_init_is_fine(self) -> None:
        code = "class Cart:\n    def __init__(self):\n        self.items = []\n"
        assert "class_mutable_attribute" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 39 — dict_fromkeys_mutable_default
# ---------------------------------------------------------------------------

class TestDictFromkeysMutable:
    def test_detects_list_default(self) -> None:
        code = "d = dict.fromkeys(['a', 'b'], [])\n"
        assert "dict_fromkeys_mutable_default" in patterns(code)

    def test_int_default_is_fine(self) -> None:
        code = "d = dict.fromkeys(['a', 'b'], 0)\n"
        assert "dict_fromkeys_mutable_default" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 40 — wrong_exception_reraise
# ---------------------------------------------------------------------------

class TestWrongExceptionReraise:
    def test_detects_raise_wrapping_caught_var(self) -> None:
        code = (
            "try:\n"
            "    f()\n"
            "except ValueError as e:\n"
            "    raise Exception(e)\n"
        )
        assert "wrong_exception_reraise" in patterns(code)

    def test_bare_raise_is_fine(self) -> None:
        code = (
            "try:\n"
            "    f()\n"
            "except ValueError:\n"
            "    raise\n"
        )
        assert "wrong_exception_reraise" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 41 — max_min_without_guard
# ---------------------------------------------------------------------------

class TestMaxMinWithoutGuard:
    def test_detects_max_no_guard(self) -> None:
        code = "def top(lst):\n    return max(lst)\n"
        assert "max_min_without_guard" in patterns(code)

    def test_with_guard_is_fine(self) -> None:
        code = (
            "def top(lst):\n"
            "    if not lst:\n"
            "        return None\n"
            "    return max(lst)\n"
        )
        assert "max_min_without_guard" not in patterns(code)

    def test_max_of_multiple_args_is_fine(self) -> None:
        code = "x = max(a, b, c)\n"
        assert "max_min_without_guard" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 42 — comparison_with_itself
# ---------------------------------------------------------------------------

class TestComparisonWithItself:
    def test_detects_x_eq_x(self) -> None:
        code = "if x == x:\n    pass\n"
        assert "comparison_with_itself" in patterns(code)

    def test_detects_x_neq_x(self) -> None:
        code = "if x != x:\n    pass\n"
        assert "comparison_with_itself" in patterns(code)

    def test_different_vars_is_fine(self) -> None:
        code = "if x == y:\n    pass\n"
        assert "comparison_with_itself" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 43 — infinite_while_no_break
# ---------------------------------------------------------------------------

class TestInfiniteWhileNoBreak:
    def test_detects_while_true_no_break(self) -> None:
        code = "while True:\n    print('hi')\n"
        assert "infinite_while_no_break" in patterns(code)

    def test_while_true_with_break_is_fine(self) -> None:
        code = "while True:\n    x = input()\n    if x == 'q':\n        break\n"
        assert "infinite_while_no_break" not in patterns(code)

    def test_while_true_with_return_is_fine(self) -> None:
        code = "def f():\n    while True:\n        return 1\n"
        assert "infinite_while_no_break" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 44 — range_excludes_last_element
# ---------------------------------------------------------------------------

class TestRangeExcludesLast:
    def test_detects_len_minus_one(self) -> None:
        code = "for i in range(len(lst) - 1):\n    pass\n"
        assert "range_excludes_last_element" in patterns(code)

    def test_range_len_full_is_fine(self) -> None:
        code = "for i in range(len(lst)):\n    pass\n"
        assert "range_excludes_last_element" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 45 — slice_wrong_direction
# ---------------------------------------------------------------------------

class TestSliceWrongDirection:
    def test_detects_constant_reverse_no_step(self) -> None:
        code = "x = lst[5:0]\n"
        assert "slice_wrong_direction" in patterns(code)

    def test_with_step_is_fine(self) -> None:
        code = "x = lst[5:0:-1]\n"
        assert "slice_wrong_direction" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 46 — callable_default_arg
# ---------------------------------------------------------------------------

class TestCallableDefaultArg:
    def test_detects_datetime_default(self) -> None:
        code = "def f(t=datetime.now()):\n    pass\n"
        assert "callable_default_arg" in patterns(code)

    def test_constant_default_is_fine(self) -> None:
        code = "def f(t=None):\n    pass\n"
        assert "callable_default_arg" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 47 — extend_with_string
# ---------------------------------------------------------------------------

class TestExtendWithString:
    def test_detects_extend_string_literal(self) -> None:
        code = "result.extend('hello')\n"
        assert "extend_with_string" in patterns(code)

    def test_extend_list_is_fine(self) -> None:
        code = "result.extend([1, 2, 3])\n"
        assert "extend_with_string" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 48 — truediv_as_index
# ---------------------------------------------------------------------------

class TestTruedivAsIndex:
    def test_detects_float_division_as_index(self) -> None:
        code = "x = lst[n/2]\n"
        assert "truediv_as_index" in patterns(code)

    def test_floor_division_is_fine(self) -> None:
        code = "x = lst[n//2]\n"
        assert "truediv_as_index" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 49 — assert_tuple
# ---------------------------------------------------------------------------

class TestAssertTuple:
    def test_detects_two_element_tuple(self) -> None:
        code = "assert (x > 0, 'must be positive')\n"
        assert "assert_tuple" in patterns(code)

    def test_correct_assert_with_msg_is_fine(self) -> None:
        code = "assert x > 0, 'must be positive'\n"
        assert "assert_tuple" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 50 — or_default_loses_falsy
# ---------------------------------------------------------------------------

class TestOrDefaultLosesFalsy:
    def test_detects_x_or_default(self) -> None:
        code = "count = count or 0\n"
        assert "or_default_loses_falsy" in patterns(code)

    def test_none_check_is_fine(self) -> None:
        code = "if count is None:\n    count = 0\n"
        assert "or_default_loses_falsy" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 51 — return_first_iteration
# ---------------------------------------------------------------------------

class TestReturnFirstIteration:
    def test_detects_unconditional_return_in_loop(self) -> None:
        code = "for x in lst:\n    return x\n"
        assert "return_first_iteration" in patterns(code)

    def test_conditional_return_is_fine(self) -> None:
        code = "for x in lst:\n    if x > 0:\n        return x\n"
        assert "return_first_iteration" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 52 — raise_in_finally
# ---------------------------------------------------------------------------

class TestRaiseInFinally:
    def test_detects_raise_in_finally(self) -> None:
        code = (
            "try:\n"
            "    f()\n"
            "finally:\n"
            "    raise ValueError('bad')\n"
        )
        assert "raise_in_finally" in patterns(code)

    def test_cleanup_in_finally_is_fine(self) -> None:
        code = (
            "try:\n"
            "    f()\n"
            "finally:\n"
            "    conn.close()\n"
        )
        assert "raise_in_finally" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 53 — while_condition_unchanged
# ---------------------------------------------------------------------------

class TestWhileConditionUnchanged:
    def test_detects_unchanging_var(self) -> None:
        code = "running = True\nwhile running:\n    x = 1\n"
        assert "while_condition_unchanged" in patterns(code)

    def test_condition_modified_is_fine(self) -> None:
        code = (
            "running = True\n"
            "while running:\n"
            "    running = False\n"
        )
        assert "while_condition_unchanged" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 54 — sort_returns_none
# ---------------------------------------------------------------------------

class TestSortReturnsNone:
    def test_detects_assigned_sort(self) -> None:
        code = "result = items.sort()\n"
        assert "sort_returns_none" in patterns(code)

    def test_standalone_sort_is_fine(self) -> None:
        code = "items.sort()\n"
        assert "sort_returns_none" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 55 — print_returns_none
# ---------------------------------------------------------------------------

class TestPrintReturnsNone:
    def test_detects_assigned_print(self) -> None:
        code = "val = print('hello')\n"
        assert "print_returns_none" in patterns(code)

    def test_standalone_print_is_fine(self) -> None:
        code = "print('hello')\n"
        assert "print_returns_none" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 56 — append_list_literal
# ---------------------------------------------------------------------------

class TestAppendListLiteral:
    def test_detects_append_list(self) -> None:
        code = "result.append([1, 2, 3])\n"
        assert "append_list_literal" in patterns(code)

    def test_extend_is_fine(self) -> None:
        code = "result.extend([1, 2, 3])\n"
        assert "append_list_literal" not in patterns(code)

    def test_append_scalar_is_fine(self) -> None:
        code = "result.append(42)\n"
        assert "append_list_literal" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 59 — len_compared_to_zero
# ---------------------------------------------------------------------------

class TestLenComparedToZero:
    def test_detects_len_eq_zero(self) -> None:
        code = "if len(lst) == 0:\n    pass\n"
        assert "len_compared_to_zero" in patterns(code)

    def test_not_x_is_fine(self) -> None:
        code = "if not lst:\n    pass\n"
        assert "len_compared_to_zero" not in patterns(code)

    def test_len_eq_nonzero_is_fine(self) -> None:
        code = "if len(lst) == 3:\n    pass\n"
        assert "len_compared_to_zero" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 60 — recursive_mutable_default
# ---------------------------------------------------------------------------

class TestRecursiveMutableDefault:
    def test_detects_recursive_with_mutable_default(self) -> None:
        code = (
            "def flatten(lst, result=[]):\n"
            "    for item in lst:\n"
            "        if isinstance(item, list):\n"
            "            flatten(item, result)\n"
            "        else:\n"
            "            result.append(item)\n"
            "    return result\n"
        )
        assert "recursive_mutable_default" in patterns(code)

    def test_none_default_in_recursive_is_fine(self) -> None:
        code = (
            "def fib(n, memo=None):\n"
            "    if memo is None: memo = {}\n"
            "    if n <= 1: return n\n"
            "    if n not in memo: memo[n] = fib(n-1, memo) + fib(n-2, memo)\n"
            "    return memo[n]\n"
        )
        assert "recursive_mutable_default" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 61 — fstring_no_interpolation
# ---------------------------------------------------------------------------

class TestFstringNoInterpolation:
    def test_detects_fstring_no_braces(self) -> None:
        code = 'msg = f"hello world"\n'
        assert "fstring_no_interpolation" in patterns(code)

    def test_fstring_with_placeholder_is_fine(self) -> None:
        code = 'msg = f"hello {name}"\n'
        assert "fstring_no_interpolation" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 62 — join_non_string_elements
# ---------------------------------------------------------------------------

class TestJoinNonStringElements:
    def test_detects_join_int_list(self) -> None:
        code = "x = ', '.join([1, 2, 3])\n"
        assert "join_non_string_elements" in patterns(code)

    def test_join_string_list_is_fine(self) -> None:
        code = "x = ', '.join(['a', 'b', 'c'])\n"
        assert "join_non_string_elements" not in patterns(code)


# ---------------------------------------------------------------------------
# Pattern 63 — sum_of_lists
# ---------------------------------------------------------------------------

class TestSumOfLists:
    def test_detects_sum_nested_lists(self) -> None:
        code = "x = sum([[1, 2], [3, 4]])\n"
        assert "sum_of_lists" in patterns(code)

    def test_sum_flat_list_is_fine(self) -> None:
        code = "x = sum([1, 2, 3, 4])\n"
        assert "sum_of_lists" not in patterns(code)
