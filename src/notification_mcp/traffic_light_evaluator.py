"""Traffic light evaluator for Agent 6 (Review & Notify).

Decision logic (agreed 2026-05-10):

    Step 1 — RED overrides (any one triggers RED immediately):
        • > 30 bugs in any single file  (file too broken for reliable AI fix)
        • > 5 files affected            (change too wide, blast radius too high)
        • AI confidence < 0.60          (AI itself is not sure)

    Step 2 — YELLOW:
        • 4–5 files affected AND ≤ 30 bugs per file AND confidence ≥ 0.60

    Step 3 — GREEN:
        • 1–3 files AND ≤ 30 bugs per file AND confidence ≥ 0.60

Human-in-the-Loop (HITL) policy:
    ALL fixes — including GREEN — require explicit human approval before merging.
    The colour signals how much scrutiny to apply, not autonomous action.
    auto_merge_allowed always returns False.

Adaptive thresholds:
    The 0.60 confidence floor self-calibrates per error type after ≥ 5 human
    approve/reject decisions via adaptive_thresholds.
"""
from __future__ import annotations

from src.shared.adaptive_thresholds import adaptive_thresholds
from src.shared.metrics import confidence_score, workflows_total
from src.shared.models import (
    CodeFix,
    FailureAnalysis,
    TrafficLightColour,
    TrafficLightResult,
)

MAX_BUGS_PER_FILE  = 30   # more than this in one file → RED
MAX_FILES_RED      = 5    # more than this many files  → RED
MAX_FILES_YELLOW   = 3    # more than this many files  → YELLOW (up to MAX_FILES_RED)
MIN_CONFIDENCE     = 0.60 # below this → RED regardless of files/bugs


def evaluate_traffic_light(
    code_fix: CodeFix,
    analysis: FailureAnalysis,
) -> TrafficLightResult:
    """Compute a TrafficLightResult using the file-count + bug-count + confidence rules."""

    num_files  = len(analysis.affected_files) if analysis.affected_files else 1
    num_bugs   = len(code_fix.bugs_found)
    confidence = code_fix.confidence

    # Bugs per file: distribute evenly as a worst-case estimate when we have
    # only a flat bug list (not per-file breakdown).
    bugs_per_file = num_bugs / max(num_files, 1)

    # Fetch adaptive confidence floor per error type
    error_type_str = (
        analysis.error_type.value
        if hasattr(analysis.error_type, "value")
        else str(analysis.error_type)
    )
    _, yellow_t = adaptive_thresholds.get_thresholds(error_type_str)
    confidence_floor = max(MIN_CONFIDENCE, yellow_t)

    blast_radius = analysis.blast_radius

    # ------------------------------------------------------------------ #
    # Step 1 — RED overrides (checked in priority order)                  #
    # ------------------------------------------------------------------ #
    if bugs_per_file > MAX_BUGS_PER_FILE:
        reason = (
            f"Too many bugs per file ({bugs_per_file:.0f} > {MAX_BUGS_PER_FILE}) — "
            "file too broken for reliable AI fix"
        )
        return _result(code_fix, TrafficLightColour.RED, confidence, reason, blast_radius)

    if num_files > MAX_FILES_RED:
        reason = (
            f"Too many files affected ({num_files} > {MAX_FILES_RED}) — "
            "change scope too wide"
        )
        return _result(code_fix, TrafficLightColour.RED, confidence, reason, blast_radius)

    if confidence < confidence_floor:
        reason = (
            f"AI confidence too low ({confidence:.0%} < {confidence_floor:.0%}) — "
            "fix blocked"
        )
        return _result(code_fix, TrafficLightColour.RED, confidence, reason, blast_radius)

    # ------------------------------------------------------------------ #
    # Step 2 — YELLOW                                                      #
    # ------------------------------------------------------------------ #
    if num_files > MAX_FILES_YELLOW:
        reason = (
            f"{num_files} files affected — careful review required "
            f"(confidence {confidence:.0%})"
        )
        return _result(code_fix, TrafficLightColour.YELLOW, confidence, reason, blast_radius)

    # ------------------------------------------------------------------ #
    # Step 3 — GREEN                                                       #
    # ------------------------------------------------------------------ #
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
    blast_radius,
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
    )
