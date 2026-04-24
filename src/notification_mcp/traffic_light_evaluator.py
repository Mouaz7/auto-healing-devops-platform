"""Traffic light evaluator for Agent 6 (Review & Notify).

Score formula:
    final_score = (llm_confidence × 0.6) + (blast_radius_score × 0.4)

Traffic light thresholds (adaptive — self-calibrate per error type):
    GREEN  ≥ adaptive_green   → auto-merge allowed   (default 0.85)
    YELLOW ≥ adaptive_yellow  → human review required (default 0.60)
    RED    < adaptive_yellow  → fix blocked

Safety override:
    HIGH blast radius ALWAYS forces RED, regardless of confidence.

The system learns from human approve/reject decisions via AdaptiveThresholds.
For example, if humans consistently approve ASSERTION_ERROR fixes at 0.70,
the GREEN threshold for that type is lowered to ~0.70 automatically.
"""
from __future__ import annotations

from src.shared.adaptive_thresholds import adaptive_thresholds
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


def evaluate_traffic_light(
    code_fix: CodeFix,
    analysis: FailureAnalysis,
) -> TrafficLightResult:
    """Compute a :class:`TrafficLightResult` from fix confidence and blast radius.

    Per-error-type thresholds are fetched from adaptive_thresholds so the
    system self-calibrates based on past human decisions.
    HIGH blast radius always triggers the safety override (RED).
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

    # Adaptive (per-error-type) thresholds — learned from human decisions
    error_type_str = (
        analysis.error_type.value
        if hasattr(analysis.error_type, "value")
        else str(analysis.error_type)
    )
    green_t, yellow_t = adaptive_thresholds.get_thresholds(error_type_str)

    if final_score >= green_t:
        colour     = TrafficLightColour.GREEN
        auto_merge = True
        reason     = f"High confidence — auto-merge allowed (threshold {green_t:.0%})"
    elif final_score >= yellow_t:
        colour     = TrafficLightColour.YELLOW
        auto_merge = False
        reason     = f"Medium confidence — human review required (threshold {yellow_t:.0%})"
    else:
        colour     = TrafficLightColour.RED
        auto_merge = False
        reason     = f"Low confidence — fix blocked (threshold {yellow_t:.0%})"

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
