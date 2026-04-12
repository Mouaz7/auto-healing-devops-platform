from __future__ import annotations

import pytest

from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
from src.shared.models import BlastRadius, TrafficLightColour


class TestTrafficLightThresholds:
    def test_green_high_confidence_low_blast(self, good_fix, low_analysis):
        # score = 0.95*0.6 + 1.0*0.4 = 0.57+0.4 = 0.97 → GREEN
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.colour == TrafficLightColour.GREEN
        assert result.auto_merge_allowed is True

    def test_yellow_medium_confidence(self, weak_fix, low_analysis):
        # score = 0.45*0.6 + 1.0*0.4 = 0.27+0.4 = 0.67 → YELLOW
        result = evaluate_traffic_light(weak_fix, low_analysis)
        assert result.colour == TrafficLightColour.YELLOW
        assert result.auto_merge_allowed is False

    def test_red_very_low_confidence(self, good_fix, low_analysis):
        from src.shared.models import CodeFix
        very_weak = CodeFix(
            build_id="b1", fix_patch="x", confidence=0.1, explanation=""
        )
        # score = 0.1*0.6 + 1.0*0.4 = 0.06+0.4 = 0.46 → RED
        result = evaluate_traffic_light(very_weak, low_analysis)
        assert result.colour == TrafficLightColour.RED
        assert result.auto_merge_allowed is False

    def test_boundary_exactly_085_is_green(self, low_analysis):
        from src.shared.models import CodeFix
        # score = x*0.6 + 1.0*0.4 = 0.85 → x = (0.85-0.4)/0.6 = 0.75
        fix = CodeFix(build_id="b1", fix_patch="", confidence=0.75, explanation="")
        result = evaluate_traffic_light(fix, low_analysis)
        assert result.colour == TrafficLightColour.GREEN

    def test_boundary_exactly_060_is_yellow(self, low_analysis):
        from src.shared.models import CodeFix
        # score = x*0.6 + 1.0*0.4 = 0.60 → x = (0.60-0.4)/0.6 = 0.333
        fix = CodeFix(build_id="b1", fix_patch="", confidence=1/3, explanation="")
        result = evaluate_traffic_light(fix, low_analysis)
        assert result.colour == TrafficLightColour.YELLOW

    def test_medium_blast_reduces_score(self):
        from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis
        fix = CodeFix(build_id="b1", fix_patch="", confidence=0.9, explanation="")
        analysis = FailureAnalysis(
            build_id="b1", error_type=ErrorType.IMPORT_ERROR,
            blast_radius=BlastRadius.MEDIUM,
        )
        # score = 0.9*0.6 + 0.6*0.4 = 0.54+0.24 = 0.78 → YELLOW
        result = evaluate_traffic_light(fix, analysis)
        assert result.colour == TrafficLightColour.YELLOW


class TestSafetyOverride:
    def test_high_blast_always_red(self, good_fix, high_analysis):
        result = evaluate_traffic_light(good_fix, high_analysis)
        assert result.colour == TrafficLightColour.RED
        assert result.safety_override is True
        assert result.auto_merge_allowed is False

    def test_high_blast_red_even_with_perfect_confidence(self, high_analysis):
        from src.shared.models import CodeFix
        perfect = CodeFix(build_id="b1", fix_patch="", confidence=1.0, explanation="")
        result = evaluate_traffic_light(perfect, high_analysis)
        assert result.colour == TrafficLightColour.RED
        assert result.safety_override is True

    def test_non_high_blast_not_overridden(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.safety_override is False


class TestResultFields:
    def test_build_id_propagated(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.build_id == good_fix.build_id

    def test_blast_radius_in_result(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.blast_radius == BlastRadius.LOW

    def test_final_score_is_rounded(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        # Should be at most 4 decimal places
        assert result.final_score == round(result.final_score, 4)

    def test_reason_not_empty(self, good_fix, low_analysis):
        result = evaluate_traffic_light(good_fix, low_analysis)
        assert result.reason != ""
