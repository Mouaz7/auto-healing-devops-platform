"""Traffic light evaluator for Agent 6 (Review & Notify).

Score formula:
    final_score = (llm_confidence × 0.6) + (blast_radius_score × 0.4)

Traffic light thresholds:
    GREEN  ≥ 0.85  → auto-merge allowed
    YELLOW 0.60–0.84 → human review required
    RED    < 0.60  → fix blocked

Safety override:
    HIGH blast radius ALWAYS forces RED, regardless of confidence.
"""
from __future__ import annotations

from src.shared.metrics import confidence_score, workflows_total
from src.shared.models import (
    BlastRadius,
    CodeFix,
    FailureAnalysis,
    TrafficLightColour,
    TrafficLightResult,
)

_BLAST_RADIUS_SCORES: dict[BlastRadius, float] = {
    BlastRadius.LOW:    1.0,
    BlastRadius.MEDIUM: 0.6,
    BlastRadius.HIGH:   0.2,
}

_GREEN_THRESHOLD  = 0.85
_YELLOW_THRESHOLD = 0.60


def evaluate_traffic_light(
    code_fix: CodeFix,
    analysis: FailureAnalysis,
) -> TrafficLightResult:
    """Compute a :class:`TrafficLightResult` from fix confidence and blast radius.

    HIGH blast radius always triggers the safety override and returns RED.
    """
    blast_score = _BLAST_RADIUS_SCORES[analysis.blast_radius]
    final_score = round(code_fix.confidence * 0.6 + blast_score * 0.4, 4)

    # Safety override — HIGH blast radius is always blocked
    if analysis.blast_radius == BlastRadius.HIGH:
        confidence_score.labels(traffic_light=TrafficLightColour.RED.value).observe(final_score)
        workflows_total.labels(status=TrafficLightColour.RED.value).inc()
        return TrafficLightResult(
            build_id=code_fix.build_id,
            colour=TrafficLightColour.RED,
            final_score=final_score,
            auto_merge_allowed=False,
            reason="Safety override: HIGH blast radius forces RED",
            blast_radius=analysis.blast_radius,
            safety_override=True,
        )

    if final_score >= _GREEN_THRESHOLD:
        colour = TrafficLightColour.GREEN
        auto_merge = True
        reason = "High confidence — auto-merge allowed"
    elif final_score >= _YELLOW_THRESHOLD:
        colour = TrafficLightColour.YELLOW
        auto_merge = False
        reason = "Medium confidence — human review required"
    else:
        colour = TrafficLightColour.RED
        auto_merge = False
        reason = "Low confidence — fix blocked"

    # Record metrics
    confidence_score.labels(traffic_light=colour.value).observe(final_score)
    workflows_total.labels(status=colour.value).inc()

    return TrafficLightResult(
        build_id=code_fix.build_id,
        colour=colour,
        final_score=final_score,
        auto_merge_allowed=auto_merge,
        reason=reason,
        blast_radius=analysis.blast_radius,
    )
