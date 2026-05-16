"""Traffic light evaluator for Agent 6 (Review & Notify).

Decision model (file count + bugs/file + AI confidence):

    Step 1 — RED overrides (any one triggers RED immediately):
        • confidence < confidence_floor (default 0.60, adaptive per error type)
        • bugs_per_file > MAX_BUGS_PER_FILE (30)
        • num_files > MAX_FILES_YELLOW (5)

    Step 2 — YELLOW:
        • 4–5 files affected, ≤30 bugs/file, confidence ≥ confidence_floor

    Step 3 — GREEN:
        • 1–3 files, ≤30 bugs/file, confidence ≥ confidence_floor

    Adaptive thresholds: the confidence_floor shifts per error type based on
    historical human approve/reject decisions (see adaptive_thresholds.py).

Human-in-the-Loop (HITL) policy:
    ALL fixes — including GREEN — require explicit human approval before merging.
    auto_merge_allowed always returns False.
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

MAX_FILES_GREEN   = 3    # 1–3 files → eligible for GREEN
MAX_FILES_YELLOW  = 5    # 4–5 files → YELLOW; >5 → RED
MAX_BUGS_PER_FILE = 30   # bugs/file above this → RED
MIN_CONFIDENCE    = 0.60 # default confidence floor (adaptive shifts this per error type)


def evaluate_traffic_light(
    code_fix: CodeFix,
    analysis: FailureAnalysis,
) -> TrafficLightResult:
    """Compute a TrafficLightResult using file count + bugs/file + confidence."""

    blast_radius  = analysis.blast_radius
    confidence    = code_fix.confidence
    num_files     = len(analysis.affected_files) if analysis.affected_files else 1
    num_bugs      = len(code_fix.bugs_found)
    error_type    = str(analysis.error_type)

    bugs_per_file = num_bugs / max(num_files, 1)

    # Adaptive confidence floor — shifts per error type based on human decisions
    _, yellow_t = adaptive_thresholds.get_thresholds(error_type)
    confidence_floor = max(MIN_CONFIDENCE, yellow_t)

    # Step 1: RED overrides (any condition blocks the fix)
    if confidence < confidence_floor:
        reason = (
            f"AI confidence too low ({confidence:.0%} < {confidence_floor:.0%}) — fix blocked"
        )
        return _result(code_fix, TrafficLightColour.RED, confidence, reason, blast_radius)

    if bugs_per_file > MAX_BUGS_PER_FILE:
        reason = (
            f"Too many bugs per file ({bugs_per_file:.0f} > {MAX_BUGS_PER_FILE}) — "
            "file too broken for reliable AI fix"
        )
        return _result(code_fix, TrafficLightColour.RED, confidence, reason, blast_radius)

    if num_files > MAX_FILES_YELLOW:
        reason = (
            f"Too many files affected ({num_files} > {MAX_FILES_YELLOW}) — "
            "change scope too wide"
        )
        return _result(code_fix, TrafficLightColour.RED, confidence, reason, blast_radius)

    # Step 2: YELLOW (4–5 files)
    if num_files > MAX_FILES_GREEN:
        reason = (
            f"{num_files} files affected — careful review required "
            f"(confidence {confidence:.0%})"
        )
        return _result(code_fix, TrafficLightColour.YELLOW, confidence, reason, blast_radius)

    # Step 3: GREEN (1–3 files)
    reason = (
        f"High confidence fix — {num_files} file(s), "
        f"{num_bugs} bug(s), confidence {confidence:.0%}"
    )
    return _result(code_fix, TrafficLightColour.GREEN, confidence, reason, blast_radius)


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
