"""Agent 2: Task Inspector — classifies tasks as Scenario A, B, or YELLOW.

Classification strategy (escalating latency):
  1. Regex heuristics (zero latency)          → fast path for obvious cases
  2. NIM LLM PRIMARY (gemma-4-31b-it)         → basic classification
  3. Fallback chain FB1→FB2→FB3               → deeper reasoning for ambiguous text
  4. If all models fail                        → YELLOW (human must decide)

Scenario mapping:
  A (BUG_FIX_FROM_COMMENT) — error keywords or stack trace patterns
  B (AUTONOMOUS_DEVELOPMENT) — feature keywords, no error signals
  YELLOW (YELLOW_MANUAL)    — ambiguous, both, or nothing matches
"""
from __future__ import annotations

import logging
import re

from src.shared.models import TaskScenario
from src.shared.nim_client import NimClient, SlotParams

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Regex heuristics
# ------------------------------------------------------------------

_BUG_RE = re.compile(
    r"\b(bug|fix|crash|traceback|failed|broken)"
    r"|(?:\w+)?(?:Error|Exception|Traceback)\b",  # NullPointerException, ImportError, etc.
    re.IGNORECASE,
)
_FEATURE_RE = re.compile(
    r"\b(feature|add|create|implement|new|enhancement|support|enable)\b",
    re.IGNORECASE,
)
_CODE_PATTERN_RE = re.compile(
    r'(```|File ".*"|line \d+|\.py:|Traceback|Error:|\bdef \b|\bclass \b)',
)

# ------------------------------------------------------------------
# LLM inference params — escalating depth per slot
# ------------------------------------------------------------------

_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (1.0,  0.95, 512),   # gemma-4 — fast, thinking enabled
    "FALLBACK_1": (0.2,  0.7,  1024),  # llama-3.3-70b — more capacity
    "FALLBACK_2": (0.6,  0.95, 2048),  # qwen3.5-122b — deep analysis
    "FALLBACK_3": (1.0,  0.95, 4096),  # mistral-large — max context
}

_SYSTEM_PROMPT = (
    "You are a task classification agent. Classify the following task as exactly "
    "one of: A, B, or YELLOW.\n\n"
    "A = Bug fix (contains error messages, stack traces, or crash reports)\n"
    "B = New feature (describes new functionality to implement, no errors)\n"
    "YELLOW = Ambiguous (mixed signals, or not enough information)\n\n"
    "Respond with ONLY the single letter: A, B, or YELLOW."
)


class TaskClassifier:
    """Classify tasks into Scenario A, B, or YELLOW.

    Args:
        nim_client: Optional NimClient for LLM-based classification.
            Pass ``None`` to use regex-only mode (tests / offline).
    """

    def __init__(self, nim_client: NimClient | None = None) -> None:
        self._nim = nim_client

    def classify(
        self,
        title: str,
        description: str,
        comments: list[str] | None = None,
    ) -> TaskScenario:
        """Classify a task into A, B, or YELLOW.

        Tries fast regex first; falls back to LLM only when ambiguous.
        """
        text = f"{title} {description} {' '.join(comments or [])}".strip()

        if not text:
            logger.debug("classify empty_text → YELLOW")
            return TaskScenario.YELLOW_MANUAL

        # Fast path — unambiguous regex match
        fast = self._regex_classify(text)
        if fast is not None:
            logger.debug("classify regex_path → %s", fast)
            return fast

        # Ambiguous → try LLM
        if self._nim is not None:
            llm_result = self._llm_classify(text)
            if llm_result is not None:
                logger.debug("classify llm_path → %s", llm_result)
                return llm_result

        logger.debug("classify fallback → YELLOW")
        return TaskScenario.YELLOW_MANUAL

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _regex_classify(self, text: str) -> TaskScenario | None:
        """Return a scenario if regex is unambiguous, else None."""
        has_bug     = bool(_BUG_RE.search(text))
        has_feature = bool(_FEATURE_RE.search(text))
        has_code    = bool(_CODE_PATTERN_RE.search(text))

        bug_signal     = has_bug or has_code
        feature_signal = has_feature

        if bug_signal and not feature_signal:
            return TaskScenario.BUG_FIX_FROM_COMMENT
        if feature_signal and not bug_signal:
            return TaskScenario.AUTONOMOUS_DEVELOPMENT
        # Both or neither — ambiguous
        return None

    def _llm_classify(self, text: str) -> TaskScenario | None:
        """Call LLM fallback chain. Returns None if all models fail."""
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": text[:3000]},
        ]
        if self._nim is None:
            return None
        try:
            response = self._nim.complete(messages)
            return _parse_llm_scenario(response)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("task_classifier llm_failed — defaulting to YELLOW")
            return None


def _parse_llm_scenario(response: str) -> TaskScenario:
    """Parse LLM response into a TaskScenario."""
    clean = response.strip().upper()
    if clean.startswith("A"):
        return TaskScenario.BUG_FIX_FROM_COMMENT
    if clean.startswith("B"):
        return TaskScenario.AUTONOMOUS_DEVELOPMENT
    return TaskScenario.YELLOW_MANUAL


def make_classifier(env_prefix: str = "TASK_INSPECTOR") -> TaskClassifier:
    """Construct a :class:`TaskClassifier` wired to the NIM API."""
    nim = NimClient(
        agent_name="task_inspector",
        agent_env_prefix=env_prefix,
        slot_params=_SLOT_PARAMS,
    )
    return TaskClassifier(nim_client=nim)
