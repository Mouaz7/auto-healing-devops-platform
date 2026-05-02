"""Unit tests for quality gates (Bandit + Pylint + evaluation)."""
from __future__ import annotations

import subprocess
import unittest.mock as mock

import pytest

from src.shared.quality_gates import (
    BanditResult,
    PylintResult,
    QualityScore,
    evaluate_quality,
    run_bandit_scan,
    run_pylint_check,
)


class TestBanditScan:
    """Test the Bandit security scanner integration."""

    def test_safe_code_passes(self):
        """Safe code with no HIGH issues should pass."""
        code = """
def safe_function(x):
    return x + 1
"""
        result = run_bandit_scan(code)
        assert isinstance(result, BanditResult)
        assert result.ok is True
        assert result.high_count == 0

    def test_hardcoded_password_is_low_severity(self):
        """Hardcoded password is LOW severity, not HIGH (so ok=True)."""
        code = """
password = "super_secret_password"
"""
        result = run_bandit_scan(code)
        # Bandit flags this as LOW, not HIGH, so ok should be True
        assert result.ok is True
        assert result.high_count == 0

    def test_result_has_issues_list(self):
        """Bandit result should include the issues list."""
        code = """
import pickle
data = pickle.loads(user_input)
"""
        result = run_bandit_scan(code)
        assert hasattr(result, "issues")
        assert isinstance(result.issues, list)


class TestPylintCheck:
    """Test the Pylint code quality checker integration."""

    def test_valid_code_passes(self):
        """Well-written code should pass."""
        code = """
def greet(name):
    return f"Hello, {name}!"
"""
        result = run_pylint_check(code)
        assert isinstance(result, PylintResult)
        assert result.ok is True
        assert result.score >= 6.0

    def test_undefined_variable_has_error(self):
        """Code with undefined variables scores below 6.0 (real Pylint formula)."""
        code = """
def broken():
    return undefined_var
"""
        result = run_pylint_check(code)
        # Pylint penalises errors with weight 5: score = 10 - (5*errors/statements)*10
        # Result is well below 6.0 → ok=False
        assert result.score < 6.0
        assert result.ok is False
        error_types = [m["type"] for m in result.messages]
        assert "error" in error_types

    def test_result_has_messages(self):
        """Pylint result should include messages list."""
        code = """
x=1+2
"""
        result = run_pylint_check(code)
        assert hasattr(result, "messages")
        assert isinstance(result.messages, list)

    def test_very_low_score_forces_low(self):
        """Code with 3+ errors should have low score."""
        code = """
def broken():
    return undefined_a + undefined_b + undefined_c + undefined_d
"""
        result = run_pylint_check(code)
        # 4 undefined variables = 4 errors → score = 10 - 4*2 = 2.0
        assert result.score <= 3.0  # Very low
        assert result.ok is False


class TestEvaluateQuality:
    """Test the combined quality evaluation."""

    def test_all_pass_returns_zero_modifier(self):
        """When both Bandit and Pylint pass, modifier should be 0."""
        bandit = BanditResult(ok=True, high_count=0, issues=[])
        pylint = PylintResult(ok=True, score=9.0, messages=[])
        quality = evaluate_quality(bandit, pylint)

        assert quality.passed is True
        assert quality.confidence_modifier == 0.0
        assert "passed" in quality.reason.lower()

    def test_bandit_high_reduces_confidence(self):
        """Bandit HIGH issue should reduce confidence by 0.30."""
        bandit = BanditResult(ok=False, high_count=1, issues=[])
        pylint = PylintResult(ok=True, score=9.0, messages=[])
        quality = evaluate_quality(bandit, pylint)

        assert quality.passed is False
        assert quality.confidence_modifier == -0.30
        assert "Bandit" in quality.reason

    def test_pylint_medium_score_reduces_confidence(self):
        """Pylint 4.0-6.0 should reduce confidence by 0.20."""
        bandit = BanditResult(ok=True, high_count=0, issues=[])
        pylint = PylintResult(ok=False, score=5.0, messages=[])
        quality = evaluate_quality(bandit, pylint)

        assert quality.passed is False
        assert quality.confidence_modifier == -0.20
        assert "Pylint score 5.0" in quality.reason

    def test_pylint_very_low_score_reduces_more(self):
        """Pylint < 4.0 should reduce confidence by 0.40."""
        bandit = BanditResult(ok=True, high_count=0, issues=[])
        pylint = PylintResult(ok=False, score=2.0, messages=[])
        quality = evaluate_quality(bandit, pylint)

        assert quality.passed is False
        assert quality.confidence_modifier == -0.40
        assert "Pylint score 2.0" in quality.reason

    def test_both_fail_stacks_penalties(self):
        """When both fail, penalties should stack."""
        bandit = BanditResult(ok=False, high_count=2, issues=[])
        pylint = PylintResult(ok=False, score=3.0, messages=[])
        quality = evaluate_quality(bandit, pylint)

        assert quality.passed is False
        # -0.30 (bandit) + -0.40 (pylint < 4.0) = -0.70
        assert quality.confidence_modifier == -0.70
        assert "Bandit" in quality.reason
        assert "Pylint" in quality.reason

    def test_reason_contains_details(self):
        """Reason should explain what failed."""
        bandit = BanditResult(ok=False, high_count=3, issues=[])
        pylint = PylintResult(ok=False, score=5.5, messages=[])
        quality = evaluate_quality(bandit, pylint)

        reason = quality.reason
        assert "3 HIGH" in reason
        assert "5.5" in reason


class TestScannerTimeout:
    """Test timeout and OSError handling in scan helpers."""

    def test_bandit_timeout_returns_ok_true(self):
        """Bandit timeout → ok=True (do not block pipeline)."""
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="bandit", timeout=30)):
            result = run_bandit_scan("x = 1")
        assert result.ok is True
        assert result.high_count == 0

    def test_pylint_timeout_returns_ok_true(self):
        """Pylint timeout → ok=True with score=8.0."""
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pylint", timeout=30)):
            result = run_pylint_check("x = 1")
        assert result.ok is True
        assert result.score == 8.0

    def test_bandit_empty_stdout_returns_ok(self):
        """Empty stdout from bandit → parsed as empty report → ok=True."""
        fake = mock.MagicMock()
        fake.stdout = ""
        with mock.patch("subprocess.run", return_value=fake):
            result = run_bandit_scan("x = 1")
        assert result.ok is True

    def test_pylint_empty_stdout_returns_ok(self):
        """Empty stdout from pylint → parsed as [] → no errors → ok=True."""
        fake = mock.MagicMock()
        fake.stdout = ""
        with mock.patch("subprocess.run", return_value=fake):
            result = run_pylint_check("x = 1")
        assert result.ok is True

    def test_bandit_malformed_json_returns_ok(self):
        """Malformed JSON from bandit → treated as empty report → ok=True."""
        fake = mock.MagicMock()
        fake.stdout = "not-json{{{broken"
        with mock.patch("subprocess.run", return_value=fake):
            result = run_bandit_scan("x = 1")
        assert result.ok is True

    def test_pylint_malformed_json_returns_ok(self):
        """Malformed JSON from pylint → treated as [] → ok=True."""
        fake = mock.MagicMock()
        fake.stdout = "not-json{{{broken"
        with mock.patch("subprocess.run", return_value=fake):
            result = run_pylint_check("x = 1")
        assert result.ok is True
