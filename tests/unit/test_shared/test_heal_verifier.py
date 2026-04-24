"""Unit tests for src.shared.heal_verifier."""
from __future__ import annotations

import time

import pytest

from src.shared.heal_verifier import HealVerifier


@pytest.fixture
def verifier():
    return HealVerifier(window_minutes=60)


class TestRecordFix:
    def test_records_build_and_files(self, verifier):
        verifier.record_fix("b-001", ["src/foo.py", "tests/test_foo.py"])
        assert "b-001" in verifier._fixes
        assert "src/foo.py" in verifier._fixes["b-001"].fixed_files

    def test_empty_files_still_records(self, verifier):
        verifier.record_fix("b-002", [])
        assert "b-002" in verifier._fixes

    def test_multiple_builds_stored_independently(self, verifier):
        verifier.record_fix("b-001", ["a.py"])
        verifier.record_fix("b-002", ["b.py"])
        assert len(verifier._fixes) == 2


class TestCheckRegression:
    def test_no_regression_when_no_fixes_recorded(self, verifier):
        result = verifier.check_regression("new-001", ["src/foo.py"])
        assert result is None

    def test_regression_detected_on_overlapping_file(self, verifier):
        verifier.record_fix("b-001", ["src/foo.py"])
        result = verifier.check_regression("b-002", ["src/foo.py"])
        assert result is not None
        assert result["original_build_id"] == "b-001"
        assert "src/foo.py" in result["overlap_files"]

    def test_no_regression_when_files_differ(self, verifier):
        verifier.record_fix("b-001", ["src/foo.py"])
        result = verifier.check_regression("b-002", ["src/bar.py"])
        assert result is None

    def test_same_build_id_not_flagged(self, verifier):
        verifier.record_fix("b-001", ["src/foo.py"])
        result = verifier.check_regression("b-001", ["src/foo.py"])
        assert result is None

    def test_age_minutes_is_positive(self, verifier):
        verifier.record_fix("b-001", ["src/foo.py"])
        result = verifier.check_regression("b-002", ["src/foo.py"])
        assert result["age_minutes"] >= 0.0

    def test_expired_fix_not_flagged(self):
        verifier = HealVerifier(window_minutes=0)  # immediate expiry
        verifier.record_fix("b-001", ["src/foo.py"])
        # manually backdate the entry to force expiry
        verifier._fixes["b-001"].merged_at = time.time() - 3600
        result = verifier.check_regression("b-002", ["src/foo.py"])
        assert result is None

    def test_empty_failing_files_returns_none(self, verifier):
        verifier.record_fix("b-001", ["src/foo.py"])
        result = verifier.check_regression("b-002", [])
        assert result is None

    def test_partial_overlap_detected(self, verifier):
        verifier.record_fix("b-001", ["a.py", "b.py", "c.py"])
        result = verifier.check_regression("b-002", ["b.py", "d.py"])
        assert result is not None
        assert "b.py" in result["overlap_files"]


class TestActiveFixesAndEviction:
    def test_active_fixes_returns_all_unexpired(self, verifier):
        verifier.record_fix("b-001", ["a.py"])
        verifier.record_fix("b-002", ["b.py"])
        active = verifier.active_fixes()
        assert len(active) == 2

    def test_expired_fixes_evicted_on_active_call(self):
        verifier = HealVerifier(window_minutes=0)
        verifier.record_fix("b-001", ["a.py"])
        verifier._fixes["b-001"].merged_at = time.time() - 7200
        active = verifier.active_fixes()
        assert len(active) == 0
