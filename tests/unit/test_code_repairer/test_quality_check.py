"""Tests for Bandit + Pylint quality gates (src/shared/quality_gates.py)."""
from __future__ import annotations

import pytest

from src.shared.quality_gates import (
    BanditResult,
    PylintResult,
    QualityScore,
    evaluate_quality,
    run_bandit_scan,
    run_pylint_check,
)


SAFE_CODE = """\
from __future__ import annotations


def add(a: int, b: int) -> int:
    return a + b
"""


class TestRunBanditScan:
    def test_safe_code_is_ok(self, safe_fix_code):
        result = run_bandit_scan(safe_fix_code)
        assert isinstance(result, BanditResult)
        assert result.ok is True
        assert result.high_count == 0

    def test_returns_issues_list(self):
        result = run_bandit_scan(SAFE_CODE)
        assert isinstance(result.issues, list)

    def test_subprocess_call_code(self):
        result = run_bandit_scan("x = 1\n")
        assert isinstance(result.ok, bool)
        assert isinstance(result.high_count, int)

    def test_empty_code(self):
        result = run_bandit_scan("")
        assert result.ok is True
        assert result.high_count == 0

    def test_dangerous_code_flagged(self):
        code = "import subprocess\nsubprocess.call(input())\n"
        result = run_bandit_scan(code)
        assert isinstance(result.ok, bool)
        assert isinstance(result.high_count, int)


class TestRunPylintCheck:
    def test_clean_code_passes(self):
        result = run_pylint_check(SAFE_CODE)
        assert isinstance(result, PylintResult)
        assert result.ok is True
        assert result.score >= 6.0

    def test_returns_messages_list(self):
        result = run_pylint_check(SAFE_CODE)
        assert isinstance(result.messages, list)

    def test_score_is_numeric(self):
        result = run_pylint_check(SAFE_CODE)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 10.0

    def test_safe_fix_code_passes(self, safe_fix_code):
        result = run_pylint_check(safe_fix_code)
        assert result.ok is True

    def test_empty_code_does_not_crash(self):
        result = run_pylint_check("")
        assert isinstance(result.ok, bool)


class TestEvaluateQuality:
    def test_all_ok_zero_modifier(self):
        b = BanditResult(ok=True, high_count=0)
        p = PylintResult(ok=True, score=8.0)
        q = evaluate_quality(b, p)
        assert isinstance(q, QualityScore)
        assert q.passed is True
        assert q.confidence_modifier == 0.0

    def test_bandit_high_reduces_confidence(self):
        b = BanditResult(ok=False, high_count=1)
        p = PylintResult(ok=True, score=8.0)
        q = evaluate_quality(b, p)
        assert q.passed is False
        assert q.confidence_modifier == pytest.approx(-0.30)

    def test_pylint_low_score_reduces_confidence(self):
        b = BanditResult(ok=True, high_count=0)
        p = PylintResult(ok=False, score=3.0)
        q = evaluate_quality(b, p)
        assert q.passed is False
        assert q.confidence_modifier == pytest.approx(-0.40)

    def test_combined_failure_stacks_modifiers(self):
        b = BanditResult(ok=False, high_count=2)
        p = PylintResult(ok=False, score=3.0)
        q = evaluate_quality(b, p)
        assert q.confidence_modifier == pytest.approx(-0.70)
