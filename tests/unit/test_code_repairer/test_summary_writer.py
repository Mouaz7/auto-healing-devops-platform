"""Tests for summary_writer — generate_summary()."""
from __future__ import annotations

from src.llm_mcp.summary_writer import generate_summary
from src.shared.models import (
    BlastRadius,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TrafficLightColour,
    TrafficLightResult,
)


def _make_inputs(
    build_id: str = "b1",
    error_type: ErrorType = ErrorType.IMPORT_ERROR,
    confidence: float = 0.9,
    colour: TrafficLightColour = TrafficLightColour.GREEN,
    files: list[str] | None = None,
    auto_merge: bool = True,
    final_score: float = 0.9,
) -> tuple[FailureAnalysis, CodeFix, TrafficLightResult]:
    analysis = FailureAnalysis(
        build_id=build_id,
        error_type=error_type,
        blast_radius=BlastRadius.LOW,
    )
    fix = CodeFix(
        build_id=build_id,
        fix_patch="code",
        confidence=confidence,
        files_to_modify=files or ["src/app.py"],
    )
    traffic = TrafficLightResult(
        build_id=build_id,
        colour=colour,
        final_score=final_score,
        auto_merge_allowed=auto_merge,
        reason="reason",
        blast_radius=BlastRadius.LOW,
    )
    return analysis, fix, traffic


class TestGenerateSummary:
    def test_contains_build_id(self):
        analysis, fix, traffic = _make_inputs(build_id="build-99")
        summary = generate_summary(analysis, fix, traffic)
        assert "build-99" in summary

    def test_contains_error_type(self):
        analysis, fix, traffic = _make_inputs(error_type=ErrorType.SYNTAX_ERROR)
        summary = generate_summary(analysis, fix, traffic)
        assert "SYNTAX_ERROR" in summary

    def test_contains_confidence_pct(self):
        analysis, fix, traffic = _make_inputs(confidence=0.92)
        summary = generate_summary(analysis, fix, traffic)
        assert "92%" in summary

    def test_contains_traffic_light_colour(self):
        analysis, fix, traffic = _make_inputs(colour=TrafficLightColour.YELLOW)
        summary = generate_summary(analysis, fix, traffic)
        assert "YELLOW" in summary

    def test_auto_merge_yes_when_true(self):
        analysis, fix, traffic = _make_inputs(auto_merge=True)
        summary = generate_summary(analysis, fix, traffic)
        assert "yes" in summary

    def test_auto_merge_no_when_false(self):
        analysis, fix, traffic = _make_inputs(auto_merge=False)
        summary = generate_summary(analysis, fix, traffic)
        assert "no" in summary

    def test_no_files_shows_unknown(self):
        """Empty files_to_modify → shows 'unknown'."""
        analysis, fix, traffic = _make_inputs()
        fix.files_to_modify = []
        summary = generate_summary(analysis, fix, traffic)
        assert "unknown" in summary

    def test_contains_score(self):
        analysis, fix, traffic = _make_inputs(final_score=0.87)
        summary = generate_summary(analysis, fix, traffic)
        assert "0.87" in summary
