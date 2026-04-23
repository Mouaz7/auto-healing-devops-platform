"""Task complexity scorer — estimates repair difficulty before calling the LLM.

The score drives model selection in model_router.py:
  LOW    → cheap 7–8 B parameter model  (fast, low cost)
  MEDIUM → mid-tier 32 B model           (balanced)
  HIGH   → heavyweight 70 B+ model       (best quality)

Scoring rules (deterministic, no LLM call needed):
  +1  for each unique affected file
  +2  if blast_radius == "HIGH"
  +1  if blast_radius == "MEDIUM"
  +3  if error_type in {IMPORT_ERROR, DEPENDENCY_ERROR, SYNTAX_ERROR, SEGFAULT}
  +2  if error_type in {TIMEOUT, MEMORY_ERROR, CONCURRENCY_ERROR}
  +1  if error_type in {TEST_FAILURE, TYPE_ERROR, ASSERTION_ERROR}
  +2  if log snippet > 1000 chars (complex trace)
  +1  if root_cause > 200 chars (verbose root cause)

Usage:
    from src.shared.task_complexity import score_complexity, Complexity

    level = score_complexity(
        error_type="IMPORT_ERROR",
        blast_radius="HIGH",
        affected_files=["src/a.py", "src/b.py"],
        root_cause="...",
        log_snippet="...",
    )
    # level.value → "LOW" | "MEDIUM" | "HIGH"
"""
from __future__ import annotations

from enum import Enum


class Complexity(str, Enum):
    """Repair task complexity level."""

    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


# Error-type point weights
_ERROR_WEIGHTS: dict[str, int] = {
    "IMPORT_ERROR":       3,
    "DEPENDENCY_ERROR":   3,
    "SYNTAX_ERROR":       3,
    "SEGFAULT":           3,
    "TIMEOUT":            2,
    "MEMORY_ERROR":       2,
    "CONCURRENCY_ERROR":  2,
    "TEST_FAILURE":       1,
    "TYPE_ERROR":         1,
    "ASSERTION_ERROR":    1,
}

# Blast-radius point weights
_RADIUS_WEIGHTS: dict[str, int] = {
    "HIGH":   2,
    "MEDIUM": 1,
    "LOW":    0,
}

# Thresholds (inclusive lower bound)
_HIGH_THRESHOLD:   int = 7
_MEDIUM_THRESHOLD: int = 3


def score_complexity(
    error_type: str,
    blast_radius: str,
    affected_files: list[str],
    root_cause: str = "",
    log_snippet: str = "",
) -> Complexity:
    """Return the repair complexity for a given failure.

    Args:
        error_type:      Normalised error type string (e.g. "ASSERTION_ERROR").
        blast_radius:    "LOW", "MEDIUM", or "HIGH".
        affected_files:  Files touched by the error.
        root_cause:      Short root-cause description.
        log_snippet:     Relevant portion of the build log.

    Returns:
        :class:`Complexity` enum value.
    """
    points = 0

    # File count
    points += len(affected_files)

    # Blast radius
    points += _RADIUS_WEIGHTS.get(blast_radius.upper(), 0)

    # Error type
    points += _ERROR_WEIGHTS.get(error_type.upper(), 0)

    # Log length
    if len(log_snippet) > 1000:
        points += 2

    # Root-cause verbosity (long = more complex)
    if len(root_cause) > 200:
        points += 1

    if points >= _HIGH_THRESHOLD:
        return Complexity.HIGH
    if points >= _MEDIUM_THRESHOLD:
        return Complexity.MEDIUM
    return Complexity.LOW
