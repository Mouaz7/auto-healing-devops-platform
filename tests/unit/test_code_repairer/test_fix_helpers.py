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
