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
        # Pure runtime error mentioning NoneType in output but as AttributeError
        code = (
            "x = None\n"
            "x.foo()\n"
        )
        ok, err = validate_fix_runtime(code)
        assert ok is False
        # AttributeError on NoneType — not the call-site pattern we redirect on
        assert "ROOT-CAUSE HINT" not in err


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
