from __future__ import annotations

import pytest

from src.notification_mcp.traffic_light_evaluator import (
    MAX_BUGS_PER_FILE,
    MAX_FILES_GREEN,
    MAX_FILES_YELLOW,
    MIN_CONFIDENCE,
    evaluate_traffic_light,
)
from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis, TrafficLightColour


def _fix(confidence: float, bugs: int = 0) -> CodeFix:
    return CodeFix(
        build_id="test-001",
        fix_patch="patch",
        confidence=confidence,
        bugs_found=["bug"] * bugs,
    )


def _analysis(files: int = 1, blast: BlastRadius = BlastRadius.LOW) -> FailureAnalysis:
    return FailureAnalysis(
        build_id="test-001",
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=blast,
        affected_files=[f"file_{i}.py" for i in range(files)],
    )


class TestGreenConditions:
    """GREEN: 1–3 files, ≤30 bugs/file, confidence ≥ 60%."""

    def test_one_file_high_confidence_is_green(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.colour == TrafficLightColour.GREEN
        assert result.auto_merge_allowed is False  # HITL always required

    def test_two_files_high_confidence_is_green(self, good_fix):
        result = evaluate_traffic_light(good_fix, _analysis(files=2))
        assert result.colour == TrafficLightColour.GREEN

    def test_three_files_high_confidence_is_green(self, good_fix):
        result = evaluate_traffic_light(good_fix, _analysis(files=MAX_FILES_GREEN))
        assert result.colour == TrafficLightColour.GREEN

    def test_exactly_060_confidence_is_green(self):
        result = evaluate_traffic_light(_fix(MIN_CONFIDENCE), _analysis(files=1))
        assert result.colour == TrafficLightColour.GREEN

    def test_blast_radius_does_not_affect_colour(self, good_fix, high_analysis):
        """HIGH blast radius no longer forces RED — colour is determined by file/bug/confidence."""
        result = evaluate_traffic_light(good_fix, high_analysis)
        assert result.colour == TrafficLightColour.GREEN
        assert result.auto_merge_allowed is False


class TestYellowConditions:
    """YELLOW: 4–5 files, ≤30 bugs/file, confidence ≥ 60%."""

    def test_four_files_is_yellow(self, good_fix):
        result = evaluate_traffic_light(good_fix, _analysis(files=MAX_FILES_GREEN + 1))
        assert result.colour == TrafficLightColour.YELLOW
        assert result.auto_merge_allowed is False

    def test_five_files_is_yellow(self, good_fix):
        result = evaluate_traffic_light(good_fix, _analysis(files=MAX_FILES_YELLOW))
        assert result.colour == TrafficLightColour.YELLOW


class TestRedConditions:
    """RED: confidence <60% OR bugs/file >30 OR files >5."""

    def test_low_confidence_is_red(self, weak_fix, low_analysis):
        # confidence=0.45 < 0.60 → RED
        result = evaluate_traffic_light(weak_fix, low_analysis)
        assert result.colour == TrafficLightColour.RED
        assert result.auto_merge_allowed is False

    def test_very_low_confidence_is_red(self):
        result = evaluate_traffic_light(_fix(0.1), _analysis())
        assert result.colour == TrafficLightColour.RED

    def test_just_below_confidence_floor_is_red(self):
        result = evaluate_traffic_light(_fix(0.599), _analysis())
        assert result.colour == TrafficLightColour.RED

    def test_six_files_is_red(self, good_fix):
        result = evaluate_traffic_light(good_fix, _analysis(files=MAX_FILES_YELLOW + 1))
        assert result.colour == TrafficLightColour.RED

    def test_too_many_bugs_per_file_is_red(self, good_fix, low_analysis):
        # 31 bugs in 1 file → 31 bugs/file > 30 → RED
        overloaded = CodeFix(
            build_id="test-001",
            fix_patch="patch",
            confidence=0.95,
            bugs_found=["bug"] * (MAX_BUGS_PER_FILE + 1),
        )
        result = evaluate_traffic_light(overloaded, low_analysis)
        assert result.colour == TrafficLightColour.RED


class TestResultFields:
    def test_build_id_propagated(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.build_id == good_fix.build_id

    def test_blast_radius_in_result(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.blast_radius == BlastRadius.LOW

    def test_final_score_is_confidence(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.final_score == round(good_fix.confidence, 4)

    def test_final_score_is_rounded(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.final_score == round(result.final_score, 4)

    def test_reason_not_empty(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.reason != ""

    def test_auto_merge_always_false(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.auto_merge_allowed is False
