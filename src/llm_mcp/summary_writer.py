"""Summary writer — placeholder for Sprint 3, full impl in Sprint 4.

Generates a human-readable summary of the fix for use in notifications.
"""
from __future__ import annotations

from src.shared.models import CodeFix, FailureAnalysis, TrafficLightResult


def generate_summary(
    analysis: FailureAnalysis,
    fix: CodeFix,
    traffic_light: TrafficLightResult,
) -> str:
    """Return a concise plain-text summary of the repair outcome."""
    files = ", ".join(fix.files_to_modify) or "unknown"
    return (
        f"Build {fix.build_id}: {analysis.error_type.value} detected "
        f"in {files}. "
        f"Fix confidence: {fix.confidence:.0%}. "
        f"Traffic light: {traffic_light.colour.value} "
        f"(score={traffic_light.final_score:.2f}). "
        f"Auto-merge: {'yes' if traffic_light.auto_merge_allowed else 'no'}."
    )
