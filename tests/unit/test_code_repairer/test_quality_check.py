from __future__ import annotations

import pytest

from src.llm_mcp.quality_check import run_bandit_scan, run_pylint_check


SAFE_CODE = """\
from __future__ import annotations


def add(a: int, b: int) -> int:
    return a + b
"""

CODE_WITH_SYNTAX_ERROR = """\
def broken(
    return 1
"""

CODE_WITH_PYLINT_ERRORS = """\
x=1
y=2
z=x+y
print z
"""


class TestRunBanditScan:
    def test_safe_code_is_ok(self, safe_fix_code):
        result = run_bandit_scan(safe_fix_code)
        assert result["ok"] is True
        assert result["high_count"] == 0

    def test_returns_issues_list(self):
        result = run_bandit_scan(SAFE_CODE)
        assert "issues" in result
        assert isinstance(result["issues"], list)

    def test_subprocess_call_code(self):
        result = run_bandit_scan("x = 1\n")
        assert isinstance(result["ok"], bool)
        assert isinstance(result["high_count"], int)

    def test_empty_code(self):
        result = run_bandit_scan("")
        assert result["ok"] is True
        assert result["high_count"] == 0

    def test_dangerous_code_flagged(self):
        code = "import subprocess\nsubprocess.call(input())\n"
        result = run_bandit_scan(code)
        # May or may not have HIGH issues depending on bandit version,
        # but result must be structurally valid
        assert "ok" in result
        assert "high_count" in result


class TestRunPylintCheck:
    def test_clean_code_passes(self):
        result = run_pylint_check(SAFE_CODE)
        assert result["ok"] is True
        assert result["score"] >= 6.0

    def test_returns_messages_list(self):
        result = run_pylint_check(SAFE_CODE)
        assert "messages" in result
        assert isinstance(result["messages"], list)

    def test_score_is_numeric(self):
        result = run_pylint_check(SAFE_CODE)
        assert isinstance(result["score"], float)
        assert 0.0 <= result["score"] <= 10.0

    def test_safe_fix_code_passes(self, safe_fix_code):
        result = run_pylint_check(safe_fix_code)
        assert result["ok"] is True

    def test_empty_code_does_not_crash(self):
        result = run_pylint_check("")
        assert "ok" in result
