"""Log cleaning pipeline for Agent 3 (Log Analyst).

Strategy:
  1. Apply regex filters in sequence (fast, deterministic, O(n)).
  2. If the reduction ratio < MIN_REDUCTION_TARGET, fall back to the NIM
     LLM (qwen/qwen2.5-coder-7b-instruct chain) to attempt deeper cleaning.
  3. Return a CleanResult with the cleaned text and metadata.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from src.log_cleaner_mcp.filters.ansi_remover import remove_ansi
from src.log_cleaner_mcp.filters.deduplicator import deduplicate
from src.log_cleaner_mcp.filters.noise_filter import filter_noise
from src.log_cleaner_mcp.filters.stack_trace_extractor import extract_stack_traces
from src.log_cleaner_mcp.filters.timestamp_stripper import strip_timestamps
from src.shared.metrics import log_reduction_ratio
from src.shared.nim_client import NimClient, SlotParams

logger = logging.getLogger(__name__)

# Target: ≥97% line reduction. If regex pipeline stays below this we try LLM.
MIN_REDUCTION_TARGET: float = 0.50

# Per-slot inference params for Agent 3 (deep log analysis)
_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (0.1, 0.7, 2048),
    "FALLBACK_1": (0.1, 0.7, 4096),
    "FALLBACK_2": (0.2, 0.7, 2048),
    "FALLBACK_3": (0.2, 0.7, 2048),
}

_LLM_SYSTEM_PROMPT = (
    "You are a log analysis expert. "
    "Given the following build log, extract only the lines that are relevant "
    "to diagnosing the build failure: error messages, exception stack traces, "
    "test failures, and critical warnings. "
    "Return ONLY the extracted lines, one per line. "
    "Do not add explanations or commentary."
)


@dataclass
class CleanResult:
    """Result of running the cleaning pipeline on a raw log."""

    original_lines: int
    cleaned_lines: int
    reduction_ratio: float   # fraction of lines removed (0–1)
    used_llm: bool
    cleaned_text: str


def _line_count(text: str) -> int:
    return sum(1 for l in text.splitlines() if l.strip())


def _apply_regex_pipeline(raw: str) -> str:
    """Run all regex filters in sequence (5-stage pipeline)."""
    text = remove_ansi(raw)           # stage 1
    text = strip_timestamps(text)     # stage 2
    text = filter_noise(text)         # stage 3
    text = deduplicate(text)          # stage 4
    extracted = extract_stack_traces(text)  # stage 5
    # Only use the extracted block if it captured something — a log that has
    # no recognisable stack trace should pass through as-is rather than
    # producing an empty result that sends Agent 4 nothing to work with.
    return extracted if extracted.strip() else text


def _llm_clean(raw: str, nim: NimClient) -> str:
    """Ask the LLM to extract failure-relevant lines from *raw*."""
    messages = [
        {"role": "system", "content": _LLM_SYSTEM_PROMPT},
        {"role": "user", "content": raw[:8000]},   # guard context window
    ]
    return nim.complete(messages)


class LogCleaningPipeline:
    """Orchestrates regex + optional LLM cleaning for build logs.

    Args:
        nim_client: Pre-configured NimClient for the log_analyst agent.
            Pass ``None`` to disable LLM fallback (useful in tests).
    """

    def __init__(self, nim_client: NimClient | None = None) -> None:
        self._nim = nim_client

    def clean(self, raw_log: str) -> CleanResult:
        """Clean *raw_log* and return a :class:`CleanResult`.

        The regex pipeline runs first. If it achieves less than
        ``MIN_REDUCTION_TARGET`` reduction *and* an LLM client is configured,
        the LLM is called as a fallback.
        """
        original_lines = _line_count(raw_log)

        regex_cleaned = _apply_regex_pipeline(raw_log)
        regex_lines = _line_count(regex_cleaned)

        reduction = (
            1.0 - regex_lines / original_lines
            if original_lines > 0
            else 1.0
        )

        if reduction >= MIN_REDUCTION_TARGET or self._nim is None:
            logger.info(
                "log_clean regex_only original=%d cleaned=%d ratio=%.2f",
                original_lines, regex_lines, reduction,
            )
            log_reduction_ratio.set(reduction * 100)
            return CleanResult(
                original_lines=original_lines,
                cleaned_lines=regex_lines,
                reduction_ratio=reduction,
                used_llm=False,
                cleaned_text=regex_cleaned,
            )

        # Regex didn't achieve target — try LLM
        logger.info(
            "log_clean llm_fallback original=%d regex_lines=%d ratio=%.2f",
            original_lines, regex_lines, reduction,
        )
        llm_text = _llm_clean(raw_log, self._nim)
        llm_lines = _line_count(llm_text)
        llm_reduction = (
            1.0 - llm_lines / original_lines
            if original_lines > 0
            else 1.0
        )

        log_reduction_ratio.set(llm_reduction * 100)
        return CleanResult(
            original_lines=original_lines,
            cleaned_lines=llm_lines,
            reduction_ratio=llm_reduction,
            used_llm=True,
            cleaned_text=llm_text,
        )


def make_pipeline(env_prefix: str = "LOG_ANALYST") -> LogCleaningPipeline:
    """Construct a :class:`LogCleaningPipeline` wired to the NIM API."""
    nim = NimClient(
        agent_name="log_analyst",
        agent_env_prefix=env_prefix,
        slot_params=_SLOT_PARAMS,
    )
    return LogCleaningPipeline(nim_client=nim)
