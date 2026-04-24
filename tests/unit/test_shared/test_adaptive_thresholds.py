"""Unit tests for src.shared.adaptive_thresholds."""
from __future__ import annotations

import pytest

from src.shared.adaptive_thresholds import (
    AdaptiveThresholds,
    _DEFAULT_GREEN,
    _DEFAULT_YELLOW,
    _GREEN_MIN,
    _MIN_DECISIONS,
)


@pytest.fixture
def thresh(tmp_path):
    return AdaptiveThresholds(path=str(tmp_path / "thresholds.jsonl"))


class TestGetThresholds:
    def test_defaults_before_any_decisions(self, thresh):
        green, yellow = thresh.get_thresholds("ASSERTION_ERROR")
        assert green == _DEFAULT_GREEN
        assert yellow == _DEFAULT_YELLOW

    def test_threshold_cached_after_first_call(self, thresh):
        thresh.get_thresholds("ASSERTION_ERROR")
        assert "ASSERTION_ERROR" in thresh._cache

    def test_cache_invalidated_after_new_decision(self, thresh):
        thresh.get_thresholds("ASSERTION_ERROR")
        assert "ASSERTION_ERROR" in thresh._cache
        thresh.record_decision("ASSERTION_ERROR", 0.75, approved=True)
        assert "ASSERTION_ERROR" not in thresh._cache


class TestRecordDecision:
    def test_record_persists_to_file(self, thresh, tmp_path):
        thresh.record_decision("ASSERTION_ERROR", 0.80, approved=True)
        files = list(tmp_path.iterdir())
        assert any(f.suffix == ".jsonl" for f in files)
        history = thresh.decision_history("ASSERTION_ERROR")
        assert len(history) == 1
        assert history[0]["approved"] is True
        assert history[0]["confidence"] == pytest.approx(0.80)

    def test_multiple_decisions_accumulate(self, thresh):
        for i in range(3):
            thresh.record_decision("TYPE_ERROR", 0.70 + i * 0.05, approved=True)
        history = thresh.decision_history("TYPE_ERROR")
        assert len(history) == 3


class TestAdaptiveCalculation:
    def test_green_threshold_lowers_after_consistent_approvals(self, thresh):
        # 5 approvals at 0.72 → green threshold should drop from 0.85
        for _ in range(_MIN_DECISIONS):
            thresh.record_decision("ASSERTION_ERROR", 0.72, approved=True)
        green, _ = thresh.get_thresholds("ASSERTION_ERROR")
        assert green < _DEFAULT_GREEN
        assert green >= _GREEN_MIN

    def test_yellow_threshold_rises_after_consistent_rejections(self, thresh):
        for _ in range(_MIN_DECISIONS):
            thresh.record_decision("IMPORT_ERROR", 0.75, approved=False)
        _, yellow = thresh.get_thresholds("IMPORT_ERROR")
        assert yellow > _DEFAULT_YELLOW

    def test_yellow_always_below_green(self, thresh):
        for _ in range(_MIN_DECISIONS):
            thresh.record_decision("TYPE_ERROR", 0.72, approved=True)
        for _ in range(_MIN_DECISIONS):
            thresh.record_decision("TYPE_ERROR", 0.70, approved=False)
        green, yellow = thresh.get_thresholds("TYPE_ERROR")
        assert yellow < green

    def test_insufficient_decisions_returns_defaults(self, thresh):
        for _ in range(_MIN_DECISIONS - 1):
            thresh.record_decision("TIMEOUT", 0.60, approved=True)
        green, yellow = thresh.get_thresholds("TIMEOUT")
        assert green == _DEFAULT_GREEN

    def test_thresholds_stay_within_safe_bounds(self, thresh):
        for _ in range(20):
            thresh.record_decision("SYNTAX_ERROR", 0.55, approved=True)
        green, yellow = thresh.get_thresholds("SYNTAX_ERROR")
        assert green >= _GREEN_MIN
        assert yellow >= 0.45


class TestSummary:
    def test_summary_empty_for_no_decisions(self, thresh):
        assert thresh.summary() == {}

    def test_summary_marks_adapted_after_enough_decisions(self, thresh):
        for _ in range(_MIN_DECISIONS):
            thresh.record_decision("ASSERTION_ERROR", 0.72, approved=True)
        s = thresh.summary()
        assert "ASSERTION_ERROR" in s
        assert s["ASSERTION_ERROR"]["adapted"] is True

    def test_summary_marks_unadapted_below_min_decisions(self, thresh):
        thresh.record_decision("ASSERTION_ERROR", 0.72, approved=True)
        s = thresh.summary()
        assert s["ASSERTION_ERROR"]["adapted"] is False
