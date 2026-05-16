"""Edge case tests for traffic light evaluator — boundary values."""
from __future__ import annotations

import pytest

from src.notification_mcp.traffic_light_evaluator import (
    MAX_BUGS_PER_FILE,
    MAX_FILES_GREEN,
    MAX_FILES_YELLOW,
    MIN_CONFIDENCE,
    evaluate_traffic_light,
)
from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis


def _fix(build_id: str, confidence: float, bugs: int = 0) -> CodeFix:
    return CodeFix(
        build_id=build_id,
        fix_patch="patch",
        confidence=confidence,
        bugs_found=["bug"] * bugs,
    )


def _analysis(build_id: str, files: int = 1, blast: BlastRadius = BlastRadius.LOW) -> FailureAnalysis:
    return FailureAnalysis(
        build_id=build_id,
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=blast,
        affected_files=[f"file_{i}.py" for i in range(files)],
    )


class TestConfidenceBoundaries:
    def test_exactly_min_confidence_is_green(self):
        """confidence == MIN_CONFIDENCE (0.60) with 1 file → GREEN."""
        fix = _fix("b1", confidence=MIN_CONFIDENCE)
        result = evaluate_traffic_light(fix, _analysis("b1", files=1))
        assert result.colour.value == "GREEN"
        assert result.final_score == MIN_CONFIDENCE
        assert result.auto_merge_allowed is False

    def test_just_below_min_confidence_is_red(self):
        """confidence = 0.599 → RED."""
        fix = _fix("b2", confidence=0.599)
        result = evaluate_traffic_light(fix, _analysis("b2", files=1))
        assert result.colour.value == "RED"

    def test_zero_confidence_is_red(self):
        """confidence = 0.0 → RED regardless of file count."""
        fix = _fix("b3", confidence=0.0)
        result = evaluate_traffic_light(fix, _analysis("b3", files=1))
        assert result.colour.value == "RED"
        assert result.auto_merge_allowed is False

    def test_perfect_confidence_one_file_is_green(self):
        """confidence = 1.0, 1 file → GREEN."""
        fix = _fix("b4", confidence=1.0)
        result = evaluate_traffic_light(fix, _analysis("b4", files=1))
        assert result.colour.value == "GREEN"
        assert result.final_score == pytest.approx(1.0, rel=1e-4)
        assert result.auto_merge_allowed is False


class TestFileBoundaries:
    def test_three_files_is_green(self):
        """MAX_FILES_GREEN (3) files → GREEN."""
        fix = _fix("b5", confidence=0.95)
        result = evaluate_traffic_light(fix, _analysis("b5", files=MAX_FILES_GREEN))
        assert result.colour.value == "GREEN"

    def test_four_files_is_yellow(self):
        """MAX_FILES_GREEN + 1 (4) files → YELLOW."""
        fix = _fix("b6", confidence=0.95)
        result = evaluate_traffic_light(fix, _analysis("b6", files=MAX_FILES_GREEN + 1))
        assert result.colour.value == "YELLOW"

    def test_five_files_is_yellow(self):
        """MAX_FILES_YELLOW (5) files → YELLOW."""
        fix = _fix("b7", confidence=0.95)
        result = evaluate_traffic_light(fix, _analysis("b7", files=MAX_FILES_YELLOW))
        assert result.colour.value == "YELLOW"

    def test_six_files_is_red(self):
        """MAX_FILES_YELLOW + 1 (6) files → RED."""
        fix = _fix("b8", confidence=0.95)
        result = evaluate_traffic_light(fix, _analysis("b8", files=MAX_FILES_YELLOW + 1))
        assert result.colour.value == "RED"
        assert result.auto_merge_allowed is False

    def test_ten_files_is_red(self):
        """10 files → RED."""
        fix = _fix("b9", confidence=0.99)
        result = evaluate_traffic_light(fix, _analysis("b9", files=10))
        assert result.colour.value == "RED"


class TestBugsPerFileBoundary:
    def test_exactly_max_bugs_per_file_is_green(self):
        """30 bugs in 1 file = MAX_BUGS_PER_FILE exactly → GREEN (boundary inclusive)."""
        fix = _fix("b10", confidence=0.95, bugs=MAX_BUGS_PER_FILE)
        result = evaluate_traffic_light(fix, _analysis("b10", files=1))
        assert result.colour.value == "GREEN"

    def test_one_over_max_bugs_per_file_is_red(self):
        """31 bugs in 1 file → RED."""
        fix = _fix("b11", confidence=0.95, bugs=MAX_BUGS_PER_FILE + 1)
        result = evaluate_traffic_light(fix, _analysis("b11", files=1))
        assert result.colour.value == "RED"

    def test_bugs_spread_across_files_not_overloaded(self):
        """60 bugs across 4 files = 15 bugs/file ≤ 30 → YELLOW (file count=4)."""
        fix = _fix("b12", confidence=0.95, bugs=60)
        result = evaluate_traffic_light(fix, _analysis("b12", files=4))
        assert result.colour.value == "YELLOW"

    def test_bugs_spread_across_files_overloaded(self):
        """62 bugs across 2 files = 31 bugs/file > 30 → RED."""
        fix = _fix("b13", confidence=0.95, bugs=62)
        result = evaluate_traffic_light(fix, _analysis("b13", files=2))
        assert result.colour.value == "RED"


class TestBlastRadiusNoLongerAffectsColour:
    """Blast radius is stored in result for reporting but does not determine colour."""

    def test_high_blast_one_file_high_confidence_is_green(self):
        """HIGH blast radius + 1 file + 95% confidence → GREEN."""
        fix = _fix("b14", confidence=0.95)
        analysis = _analysis("b14", files=1, blast=BlastRadius.HIGH)
        result = evaluate_traffic_light(fix, analysis)
        assert result.colour.value == "GREEN"
        assert result.safety_override is False

    def test_medium_blast_does_not_reduce_score(self):
        """MEDIUM blast does not change final_score (it equals confidence now)."""
        fix = _fix("b15", confidence=0.9)
        low = _analysis("b15", files=1, blast=BlastRadius.LOW)
        med = _analysis("b15", files=1, blast=BlastRadius.MEDIUM)
        result_low = evaluate_traffic_light(fix, low)
        result_med = evaluate_traffic_light(fix, med)
        assert result_low.final_score == result_med.final_score
        assert result_low.colour == result_med.colour

    def test_blast_radius_preserved_in_result(self):
        """blast_radius is still recorded in TrafficLightResult for audit."""
        fix = _fix("b16", confidence=0.95)
        analysis = _analysis("b16", files=1, blast=BlastRadius.HIGH)
        result = evaluate_traffic_light(fix, analysis)
        assert result.blast_radius == BlastRadius.HIGH
