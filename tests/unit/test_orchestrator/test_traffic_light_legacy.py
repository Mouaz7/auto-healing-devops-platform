"""Tests for legacy orchestrator traffic_light.py (Sprint 2 helper)."""
from __future__ import annotations

from src.orchestrator_mcp.traffic_light import evaluate
from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis


def _inputs(build_id: str, a_conf: float, f_conf: float, blast: BlastRadius):
    analysis = FailureAnalysis(
        build_id=build_id,
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=blast,
        confidence=a_conf,
    )
    fix = CodeFix(build_id=build_id, fix_patch="patch", confidence=f_conf)
    return analysis, fix


class TestEvaluateLegacy:
    def test_high_combined_confidence_green(self):
        """Combined confidence ≥ 0.85 → GREEN."""
        analysis, fix = _inputs("b1", 0.9, 0.9, BlastRadius.LOW)
        result = evaluate("b1", analysis, fix)
        assert result.colour.value == "GREEN"
        assert result.auto_merge_allowed is True

    def test_medium_combined_confidence_yellow(self):
        """Combined confidence 0.60–0.84 → YELLOW."""
        analysis, fix = _inputs("b2", 0.7, 0.7, BlastRadius.LOW)
        result = evaluate("b2", analysis, fix)
        assert result.colour.value == "YELLOW"
        assert result.auto_merge_allowed is False

    def test_low_combined_confidence_red(self):
        """Combined confidence < 0.60 → RED."""
        analysis, fix = _inputs("b3", 0.3, 0.3, BlastRadius.LOW)
        result = evaluate("b3", analysis, fix)
        assert result.colour.value == "RED"

    def test_high_blast_radius_forces_red(self):
        """HIGH blast radius always forces RED."""
        analysis, fix = _inputs("b4", 0.95, 0.95, BlastRadius.HIGH)
        result = evaluate("b4", analysis, fix)
        assert result.colour.value == "RED"
        assert result.safety_override is True

    def test_build_id_in_result(self):
        """build_id propagated to result."""
        analysis, fix = _inputs("build-xyz", 0.8, 0.8, BlastRadius.LOW)
        result = evaluate("build-xyz", analysis, fix)
        assert result.build_id == "build-xyz"

    def test_final_score_is_average(self):
        """final_score = (analysis.confidence + fix.confidence) / 2."""
        analysis, fix = _inputs("b5", 0.8, 0.6, BlastRadius.LOW)
        result = evaluate("b5", analysis, fix)
        assert result.final_score == pytest.approx(0.70, rel=1e-4)


import pytest  # noqa: E402 — needed for approx above
