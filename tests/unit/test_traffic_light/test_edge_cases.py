"""Edge case tests for traffic light evaluator — boundary values."""
from __future__ import annotations

import pytest

from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis


def _fix(build_id: str, confidence: float) -> CodeFix:
    return CodeFix(build_id=build_id, fix_patch="patch", confidence=confidence)


def _analysis(build_id: str, blast: BlastRadius) -> FailureAnalysis:
    return FailureAnalysis(
        build_id=build_id,
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=blast,
    )


class TestBoundaryValues:
    def test_green_at_exactly_085(self):
        """final_score = 0.85 exactly → GREEN (not YELLOW)."""
        # 0.85*0.6 + 1.0*0.4 = 0.51 + 0.40 = 0.91 → too high
        # Need: confidence*0.6 + 1.0*0.4 = 0.85
        # confidence = (0.85 - 0.40) / 0.6 = 0.75
        fix = _fix("b1", confidence=0.75)
        analysis = _analysis("b1", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score == pytest.approx(0.85, rel=1e-4)
        assert result.colour.value == "GREEN"
        assert result.auto_merge_allowed is False  # HITL: human approval always required

    def test_yellow_at_exactly_060(self):
        """final_score = 0.60 exactly → YELLOW (not RED)."""
        # confidence*0.6 + 1.0*0.4 = 0.60
        # confidence = (0.60 - 0.40) / 0.6 = 0.3333...
        fix = _fix("b2", confidence=1 / 3)
        analysis = _analysis("b2", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score == pytest.approx(0.60, abs=0.005)
        assert result.colour.value in ("YELLOW", "RED")  # boundary ≥0.60 → YELLOW

    def test_yellow_just_above_060(self):
        """final_score = 0.601 → YELLOW."""
        # Confidence that produces score just above 0.60
        # 0.34*0.6 + 1.0*0.4 = 0.204 + 0.40 = 0.604 → YELLOW
        fix = _fix("b3", confidence=0.34)
        analysis = _analysis("b3", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score >= 0.60
        assert result.colour.value == "YELLOW"

    def test_red_at_059(self):
        """final_score < 0.60 → RED."""
        # 0.2*0.6 + 1.0*0.4 = 0.12 + 0.40 = 0.52 → RED
        fix = _fix("b4", confidence=0.2)
        analysis = _analysis("b4", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score < 0.60
        assert result.colour.value == "RED"
        assert result.auto_merge_allowed is False

    def test_green_just_below_085_is_yellow(self):
        """final_score = 0.849 → YELLOW (not GREEN)."""
        # 0.74*0.6 + 1.0*0.4 = 0.444 + 0.40 = 0.844 → YELLOW
        fix = _fix("b5", confidence=0.74)
        analysis = _analysis("b5", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score < 0.85
        assert result.colour.value == "YELLOW"


class TestHighBlastRadius:
    def test_high_blast_with_perfect_confidence_is_red(self):
        """llm_confidence=1.0 + blast_radius=HIGH → always RED."""
        fix = _fix("b6", confidence=1.0)
        analysis = _analysis("b6", BlastRadius.HIGH)
        result = evaluate_traffic_light(fix, analysis)
        assert result.colour.value == "RED"
        assert result.auto_merge_allowed is False
        assert result.safety_override is True

    def test_high_blast_with_zero_confidence_is_red(self):
        """confidence=0.0 + blast_radius=HIGH → RED with safety override."""
        fix = _fix("b7", confidence=0.0)
        analysis = _analysis("b7", BlastRadius.HIGH)
        result = evaluate_traffic_light(fix, analysis)
        assert result.colour.value == "RED"
        assert result.safety_override is True

    def test_high_blast_safety_override_flag_set(self):
        """safety_override must be True for HIGH blast radius."""
        fix = _fix("b8", confidence=0.99)
        analysis = _analysis("b8", BlastRadius.HIGH)
        result = evaluate_traffic_light(fix, analysis)
        assert result.safety_override is True

    def test_medium_blast_not_overridden(self):
        """MEDIUM blast radius should NOT trigger safety override."""
        fix = _fix("b9", confidence=0.99)
        analysis = _analysis("b9", BlastRadius.MEDIUM)
        result = evaluate_traffic_light(fix, analysis)
        assert result.safety_override is False


class TestZeroAndMaxConfidence:
    def test_zero_confidence_low_blast_is_red(self):
        """confidence=0.0 + LOW blast → final_score=0.40 → RED."""
        fix = _fix("b10", confidence=0.0)
        analysis = _analysis("b10", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score == pytest.approx(0.40, rel=1e-4)
        assert result.colour.value == "RED"

    def test_perfect_confidence_low_blast_is_green(self):
        """confidence=1.0 + LOW blast → final_score=1.0 → GREEN."""
        fix = _fix("b11", confidence=1.0)
        analysis = _analysis("b11", BlastRadius.LOW)
        result = evaluate_traffic_light(fix, analysis)
        assert result.final_score == pytest.approx(1.0, rel=1e-4)
        assert result.colour.value == "GREEN"
        assert result.auto_merge_allowed is False  # HITL: human approval always required

    def test_medium_blast_reduces_score(self):
        """MEDIUM blast (score=0.6) reduces final_score vs LOW blast."""
        fix = _fix("b12", confidence=0.9)
        low = _analysis("b12", BlastRadius.LOW)
        med = _analysis("b12", BlastRadius.MEDIUM)
        result_low = evaluate_traffic_light(fix, low)
        result_med = evaluate_traffic_light(fix, med)
        assert result_low.final_score > result_med.final_score
