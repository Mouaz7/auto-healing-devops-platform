"""Tests for fix-generator helpers — NoneType hint + error fingerprinting."""
from __future__ import annotations

from src.llm_mcp.fix_prompts import _error_fingerprint, build_retry_prompt
from src.llm_mcp.fix_validators import validate_fix_runtime


# ---------------------------------------------------------------------------
# validate_fix_runtime — NoneType ROOT-CAUSE HINT
# ---------------------------------------------------------------------------

class TestValidateFixRuntimeHint:
    def test_typeerror_with_nonetype_appends_root_cause_hint(self) -> None:
        """A TypeError naming NoneType should redirect the LLM to call sites."""
        code = (
            "def f(a, b=None):\n"
            "    return a < b\n"
            "f(1)\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "TypeError" in err
        assert "ROOT-CAUSE HINT" in err
        assert "CALL SITE" in err

    def test_plain_syntax_error_does_not_get_hint(self) -> None:
        """SyntaxErrors should not trigger the call-site hint (false-positive guard)."""
        # SyntaxError fails at AST parse stage — but validate_fix_runtime gets
        # invalid code that passed AST. Use a NameError instead which runs but
        # does not involve NoneType.
        code = (
            "def f():\n"
            "    return undefined_var\n"
            "f()\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "NameError" in err
        assert "ROOT-CAUSE HINT" not in err

    def test_nonetype_without_typeerror_does_not_get_hint(self) -> None:
        """The hint requires BOTH 'NoneType' and 'TypeError' to fire."""
        code = (
            "x = None\n"
            "x.foo()\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "ROOT-CAUSE HINT" not in err

    def test_indexerror_out_of_range_appends_offbyone_hint(self) -> None:
        """IndexError 'list index out of range' → off-by-one hint."""
        code = (
            "def avg(nums):\n"
            "    total = 0\n"
            "    for i in range(len(nums) + 1):\n"
            "        total += nums[i]\n"
            "    return total / len(nums)\n"
            "avg([1, 2, 3])\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "IndexError" in err
        assert "OFF-BY-ONE HINT" in err
        assert "range(len(x) + 1)" in err

    def test_assertionerror_appends_silent_bug_hint(self) -> None:
        """AssertionError (wrong output) → silent bug hint with operator guidance."""
        code = (
            "def avg(nums):\n"
            "    total = 0.0\n"
            "    for num in nums:\n"
            "        total == num\n"   # comparison not accumulation
            "    return total / len(nums)\n"
            "result = avg([1, 2, 3])\n"
            "assert result == 2.0, f'Expected 2.0, got {result}'\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "AssertionError" in err
        assert "SILENT BUG HINT" in err
        assert "Wrong operator" in err
        assert "+=" in err

    def test_wrong_return_value_assertionerror_hint(self) -> None:
        """return 1 on empty list triggers AssertionError → silent bug hint."""
        code = (
            "def avg(nums):\n"
            "    if not nums:\n"
            "        return 1\n"
            "    return sum(nums) / len(nums)\n"
            "result = avg([])\n"
            "assert result == 0, f'Expected 0, got {result}'\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "SILENT BUG HINT" in err
        assert "Wrong return value" in err

    def test_clean_code_gets_no_hints(self) -> None:
        """Correct code should pass with no hints appended."""
        code = (
            "def avg(nums):\n"
            "    if not nums:\n"
            "        return 0.0\n"
            "    return sum(nums) / len(nums)\n"
            "avg([1, 2, 3])\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is True
        assert err == ""

    def test_recursionerror_appends_recursion_hint(self) -> None:
        """RecursionError → hint about base case and convergence."""
        code = (
            "def fib(n):\n"
            "    if n == 1:\n"          # misses n=0
            "        return n\n"
            "    return fib(n-1) + fib(n-2)\n"
            "fib(0)\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "RecursionError" in err or "maximum recursion" in err.lower()
        assert "RECURSION HINT" in err
        assert "base case" in err.lower()
        assert "n <= 1" in err

    def test_attributeerror_nonetype_appends_missing_return_hint(self) -> None:
        """AttributeError NoneType → hint about missing return in recursive call."""
        code = (
            "class Node:\n"
            "    def __init__(self, val, nxt=None):\n"
            "        self.val = val\n"
            "        self.next = nxt\n"
            "    def find(self, t):\n"
            "        if self.val == t: return self\n"
            "        if self.next: self.next.find(t)\n"   # missing return
            "        return None\n"
            "n = Node(1, Node(2, Node(3)))\n"
            "print(n.find(3).val)\n"    # AttributeError: NoneType.val
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "AttributeError" in err
        assert "MISSING RETURN HINT" in err
        assert "return self.next.find" in err

    def test_keyerror_appends_key_guard_hint(self) -> None:
        """KeyError → hint about checking key existence before access."""
        code = (
            "memo = {}\n"
            "def fib(n):\n"
            "    if n <= 1: return n\n"
            "    result = memo[n]\n"     # KeyError: n not yet in memo
            "    if result is None:\n"
            "        memo[n] = fib(n-1) + fib(n-2)\n"
            "    return memo[n]\n"
            "fib(5)\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "KeyError" in err
        assert "MISSING KEY GUARD HINT" in err
        assert "memo.get" in err or "not in memo" in err

    def test_zerodivisionerror_appends_zero_division_hint(self) -> None:
        """ZeroDivisionError → hint about adding a guard before dividing."""
        code = (
            "def avg(nums):\n"
            "    return sum(nums) / len(nums)\n"
            "avg([])\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        assert "ZeroDivisionError" in err
        assert "ZERO DIVISION HINT" in err
        assert "if not" in err

    def test_infinite_loop_hint_in_timeout_message(self) -> None:
        """Timeout → improved message with binary search and loop guidance."""
        code = (
            "def search(arr, target):\n"
            "    low, high = 0, len(arr) - 1\n"
            "    while low <= high:\n"
            "        mid = (low + high) // 2\n"
            "        if arr[mid] == target: return mid\n"
            "        elif arr[mid] < target: low = mid\n"   # never advances
            "        else: high = mid\n"
            "    return -1\n"
            "search([1,2,3,4,5], 5)\n"
        )
        ok, err = validate_fix_runtime(code, timeout_s=3)
        assert ok is False
        assert "INFINITE LOOP" in err
        assert "INFINITE LOOP HINT" in err
        assert "mid + 1" in err


# ---------------------------------------------------------------------------
# _error_fingerprint — normalisation
# ---------------------------------------------------------------------------

class TestErrorFingerprint:
    def test_strips_tmp_paths(self) -> None:
        a = 'File "/tmp/abc123.py", line 5\nTypeError: bad operand'
        b = 'File "/tmp/zzz999.py", line 8\nTypeError: bad operand'
        assert _error_fingerprint(a) == _error_fingerprint(b)

    def test_different_error_types_differ(self) -> None:
        a = "TypeError: bad operand"
        b = "ValueError: bad operand"
        assert _error_fingerprint(a) != _error_fingerprint(b)

    def test_falls_back_to_prefix_when_no_match(self) -> None:
        """No 'XxxError' pattern → first 80 chars used as fingerprint."""
        s = "some unrelated stderr blob without standard error class"
        assert _error_fingerprint(s) == s[:80]


# ---------------------------------------------------------------------------
# build_retry_prompt — STRATEGY PIVOT trigger
# ---------------------------------------------------------------------------

class TestBuildRetryPromptPivot:
    def test_two_typeerrors_with_different_tmp_paths_trigger_pivot(self) -> None:
        """Same root cause, different tmp filenames → pivot text appears."""
        attempts = [
            {"attempt": 0, "kind": "runtime", "fix_preview": "x",
             "err": ('File "/tmp/aaa.py", line 17, in f\n'
                     "TypeError: '<' not supported between 'int' and 'NoneType'")},
            {"attempt": 1, "kind": "runtime", "fix_preview": "x",
             "err": ('File "/tmp/bbb.py", line 17, in f\n'
                     "TypeError: '<' not supported between 'int' and 'NoneType'")},
        ]
        prompt = build_retry_prompt("orig", attempts)
        assert "STRATEGY PIVOT REQUIRED" in prompt
        assert "CALL SITE" in prompt

    def test_different_error_types_do_not_trigger_pivot(self) -> None:
        """SyntaxError followed by TypeError → no pivot (real progress)."""
        attempts = [
            {"attempt": 0, "kind": "syntax", "fix_preview": "x",
             "err": "SyntaxError: invalid syntax"},
            {"attempt": 1, "kind": "runtime", "fix_preview": "x",
             "err": "TypeError: bad operand"},
        ]
        prompt = build_retry_prompt("orig", attempts)
        assert "STRATEGY PIVOT REQUIRED" not in prompt

    def test_single_attempt_does_not_trigger_pivot(self) -> None:
        """Need at least 2 attempts to detect a loop."""
        attempts = [{"attempt": 0, "kind": "runtime", "fix_preview": "x",
                     "err": "TypeError: bad"}]
        prompt = build_retry_prompt("orig", attempts)
        assert "STRATEGY PIVOT REQUIRED" not in prompt

    def test_two_syntax_errors_trigger_structure_pivot(self) -> None:
        """Repeated SyntaxErrors should ask for full rewrite, not call sites."""
        attempts = [
            {"attempt": 0, "kind": "syntax", "fix_preview": "x",
             "err": "SyntaxError on line 11: unexpected indent"},
            {"attempt": 1, "kind": "syntax", "fix_preview": "x",
             "err": "SyntaxError on line 11: unexpected indent"},
        ]
        prompt = build_retry_prompt("orig", attempts)
        assert "STRUCTURE BROKEN" in prompt
        assert "ENTIRE corrected file" in prompt
        # The call-site language MUST NOT appear in this branch — wrong advice
        assert "call site" not in prompt.lower()

    def test_two_runtime_errors_still_get_call_site_pivot(self) -> None:
        """Make sure the runtime branch is unaffected by the new syntax branch."""
        attempts = [
            {"attempt": 0, "kind": "runtime", "fix_preview": "x",
             "err": "TypeError: '<' not supported between 'int' and 'NoneType'"},
            {"attempt": 1, "kind": "runtime", "fix_preview": "x",
             "err": "TypeError: '<' not supported between 'int' and 'NoneType'"},
        ]
        prompt = build_retry_prompt("orig", attempts)
        assert "STRATEGY PIVOT REQUIRED" in prompt
        assert "CALL SITE" in prompt
        assert "STRUCTURE BROKEN" not in prompt
