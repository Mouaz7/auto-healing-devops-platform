"""Model router — selects the cheapest model tier for a given complexity level.

Works with the 4-slot NimClient fallback chain.  For LOW complexity tasks the
router overrides the PRIMARY slot with a cheap 7–8 B model; for MEDIUM it uses
a 32 B model; for HIGH it lets the default heavyweight config run unchanged.

This reduces token cost without sacrificing quality on simple fixes — important
for a platform that may process hundreds of builds per day.

Usage:
    from src.shared.model_router import route_model
    from src.shared.task_complexity import Complexity

    slot_overrides = route_model(Complexity.LOW)
    # e.g. {"PRIMARY": "qwen/qwen2.5-coder-7b-instruct"}
    nim_client.complete(messages, slot_overrides=slot_overrides)
"""
from __future__ import annotations

import logging
import os

from src.shared.task_complexity import Complexity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model catalogue — ordered cheapest → most capable
# ---------------------------------------------------------------------------

_MODEL_TIERS: dict[Complexity, dict[str, str]] = {
    Complexity.LOW: {
        "PRIMARY":    os.getenv("MODEL_LOW_PRIMARY",    "qwen/qwen2.5-coder-7b-instruct"),
        "FALLBACK_1": os.getenv("MODEL_LOW_FALLBACK_1", "google/gemma-3-12b-it"),
    },
    Complexity.MEDIUM: {
        "PRIMARY":    os.getenv("MODEL_MED_PRIMARY",    "qwen/qwen2.5-coder-32b-instruct"),
        "FALLBACK_1": os.getenv("MODEL_MED_FALLBACK_1", "meta/llama-3.1-70b-instruct"),
    },
    Complexity.HIGH: {
        # HIGH uses the default heavyweight chain from AGENT_CONFIGS — no override
    },
}


def route_model(complexity: Complexity) -> dict[str, str]:
    """Return slot→model-id overrides for the given complexity level.

    Returns an empty dict for HIGH complexity so the caller's default
    heavyweight configuration is used unchanged.

    Args:
        complexity: Complexity enum value from :mod:`src.shared.task_complexity`.

    Returns:
        Dict mapping slot names to NIM model IDs.  Empty dict = use defaults.
    """
    overrides = _MODEL_TIERS.get(complexity, {})
    logger.info("model_router complexity=%s overrides=%s", complexity.value, list(overrides))
    return overrides


def complexity_label(complexity: Complexity) -> str:
    """Return a human-readable description of the model choice for logging."""
    if complexity == Complexity.LOW:
        return "cheap 7–8 B model (LOW complexity)"
    if complexity == Complexity.MEDIUM:
        return "mid-tier 32 B model (MEDIUM complexity)"
    return "heavyweight 70 B+ model (HIGH complexity)"
