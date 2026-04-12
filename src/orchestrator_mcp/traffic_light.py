"""Traffic light evaluator — placeholder for Sprint 2, full impl in Sprint 3.

Sprint 3 will wire in Agent 6 (Review & Notify) confidence scores and
blast-radius logic to produce TrafficLightResult objects.
"""
from __future__ import annotations

from src.shared.models import (
    BlastRadius,
    CodeFix,
    FailureAnalysis,
    TrafficLightColour,
    TrafficLightResult,
)

_GREEN_THRESHOLD = 0.85
_YELLOW_THRESHOLD = 0.60


def evaluate(build_id: str, analysis: FailureAnalysis,
             fix: CodeFix) -> TrafficLightResult:
    """Compute a traffic-light result from analysis + fix confidence.

    HIGH blast radius always forces RED regardless of confidence score.
    Sprint 2: returns a deterministic result based on combined confidence.
    Sprint 3: integrates Agent 6 LLM review score.
    """
    combined = (analysis.confidence + fix.confidence) / 2
    safety_override = analysis.blast_radius == BlastRadius.HIGH

    if safety_override or combined < _YELLOW_THRESHOLD:
        colour = TrafficLightColour.RED
    elif combined < _GREEN_THRESHOLD:
        colour = TrafficLightColour.YELLOW
    else:
        colour = TrafficLightColour.GREEN

    return TrafficLightResult(
        build_id=build_id,
        colour=colour,
        final_score=round(combined, 4),
        auto_merge_allowed=(colour == TrafficLightColour.GREEN),
        reason="Combined confidence score" + (" [HIGH blast radius override]" if safety_override else ""),
        blast_radius=analysis.blast_radius,
        safety_override=safety_override,
    )
