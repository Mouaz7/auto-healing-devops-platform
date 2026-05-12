"""Traffic light evaluator for Agent 6 (Review & Notify).

Scoring model:
    final_score = confidence * 0.6 + blast_factor * 0.4

    blast_factor:
        HIGH   → 0.0  (and always forces RED with safety_override=True)
        MEDIUM → 0.6
        LOW    → 1.0

    Thresholds:
        final_score ≥ 0.85 → GREEN
        final_score ≥ 0.60 → YELLOW
        final_score < 0.60 → RED

    Bug overload: bugs_per_file > MAX_BUGS_PER_FILE → RED regardless of score.

Human-in-the-Loop (HITL) policy:
    ALL fixes — including GREEN — require explicit human approval before merging.
    auto_merge_allowed always returns False.
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

MAX_BUGS_PER_FILE = 30   # more than this in one file → RED
GREEN_THRESHOLD   = 0.85
YELLOW_THRESHOLD  = 0.60

_BLAST_FACTOR: dict[BlastRadius, float] = {
    BlastRadius.LOW:    1.0,
    BlastRadius.MEDIUM: 0.6,
    BlastRadius.HIGH:   0.0,
}


def evaluate_traffic_light(
    code_fix: CodeFix,
    analysis: FailureAnalysis,
) -> TrafficLightResult:
    """Compute a TrafficLightResult using the weighted scoring model."""

    blast_radius = analysis.blast_radius
    confidence   = code_fix.confidence
    num_files    = len(analysis.affected_files) if analysis.affected_files else 1
    num_bugs     = len(code_fix.bugs_found)

    # HIGH blast radius always forces RED with safety override.
    if blast_radius == BlastRadius.HIGH:
        blast_factor = _BLAST_FACTOR[BlastRadius.HIGH]
        final_score  = round(confidence * 0.6 + blast_factor * 0.4, 4)
        reason = (
            f"HIGH blast radius — safety override engaged "
            f"(confidence {confidence:.0%}, score {final_score:.2f})"
        )
        return _result(
            code_fix, TrafficLightColour.RED, final_score,
            reason, blast_radius, safety_override=True,
        )

    blast_factor = _BLAST_FACTOR.get(blast_radius, 1.0)
    final_score  = round(confidence * 0.6 + blast_factor * 0.4, 4)

    # Bug overload check.
    bugs_per_file = num_bugs / max(num_files, 1)
    if bugs_per_file > MAX_BUGS_PER_FILE:
        reason = (
            f"Too many bugs per file ({bugs_per_file:.0f} > {MAX_BUGS_PER_FILE}) — "
            "file too broken for reliable AI fix"
        )
        return _result(code_fix, TrafficLightColour.RED, final_score, reason, blast_radius)

    # Score-based classification.
    if final_score >= GREEN_THRESHOLD:
        colour = TrafficLightColour.GREEN
        reason = (
            f"High confidence fix — {num_files} file(s), "
            f"{num_bugs} bug(s), score {final_score:.2f}"
        )
    elif final_score >= YELLOW_THRESHOLD:
        colour = TrafficLightColour.YELLOW
        reason = (
            f"Moderate confidence — {num_files} file(s), "
            f"score {final_score:.2f}, careful review required"
        )
    else:
        colour = TrafficLightColour.RED
        reason = (
            f"Score too low ({final_score:.2f} < {YELLOW_THRESHOLD}) — "
            f"confidence {confidence:.0%} fix blocked"
        )

    return _result(code_fix, colour, final_score, reason, blast_radius)


def _result(
    code_fix: CodeFix,
    colour: TrafficLightColour,
    final_score: float,
    reason: str,
    blast_radius: BlastRadius,
    safety_override: bool = False,
) -> TrafficLightResult:
    confidence_score.labels(traffic_light=colour.value).observe(final_score)
    workflows_total.labels(status=colour.value).inc()
    return TrafficLightResult(
        build_id=code_fix.build_id,
        colour=colour,
        final_score=round(final_score, 4),
        auto_merge_allowed=False,
        reason=reason,
        blast_radius=blast_radius,
        safety_override=safety_override,
    )
