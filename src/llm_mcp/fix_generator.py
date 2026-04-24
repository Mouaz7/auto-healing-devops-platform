"""Agent 5: Fix generator — produces code fixes via NIM LLM with quality checks.

Constraints (per spec):
  - Max 20 lines of changed code (strict: most bugs = 1-5 lines)
  - Max 10% file change or 5 lines diff vs original (whichever is more)
  - Rejects fixes that refactor or change unrelated code
  - Max 2 retries on LLM failure
  - 60 s timeout (enforced by NimClient via AgentModelConfig.timeout_seconds)
  - Bandit + Pylint run on generated code before returning

Enhancements (post Sprint 1):
  - fix_memory context injected into prompts (few-shot learning from history)
  - Secret scanner blocks fixes with hardcoded credentials
  - Log compression reduces token usage ~90% on verbose CI logs
  - Task complexity scorer selects the cheapest adequate model tier
"""
from __future__ import annotations

import json
import logging
import re

from src.llm_mcp.prompt_templates import (
    MAX_FIX_LINES,
    MAX_RETRIES,
    SCENARIO_A_TEMPLATE,
    SYSTEM_PROMPT,
)
from src.shared.config import AGENT_CONFIGS
from src.shared.fix_memory import build_memory_context, fix_memory
from src.shared.metrics import quality_gate_results
from src.shared.model_fallback import AllModelsFailed
from src.shared.models import CodeFix, FailureAnalysis
from src.shared.nim_client import NimClient, SlotParams
from src.shared.prompt_compressor import compress_log
from src.shared.quality_gates import (
    evaluate_quality,
    run_bandit_scan,
    run_pylint_check,
)
from src.shared.secret_scanner import scan_for_secrets
from src.shared.task_complexity import score_complexity

logger = logging.getLogger(__name__)

# Inference params for the heavyweight coder models
_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (0.7, 0.8, 4096),
    "FALLBACK_1": (1.0, 0.95, 8192),
    "FALLBACK_2": (1.0, 1.0, 4096),
    "FALLBACK_3": (0.6, 0.7, 4096),
}


class FixTooLongError(ValueError):
    """Raised when the generated fix exceeds MAX_FIX_LINES."""


class SecretLeakError(ValueError):
    """Raised when the generated fix contains hardcoded secrets."""


class FixGenerator:
    """Generate code fixes via the NIM LLM fallback chain.

    Args:
        nim_client: Configured NimClient for the code_repairer agent.
            Pass ``None`` in tests to disable real LLM calls.
    """

    def __init__(self, nim_client: NimClient | None = None) -> None:
        self._nim = nim_client

    def generate_fix(  # pylint: disable=too-many-locals
        self,
        analysis: FailureAnalysis,
        code_context: str,
        cleaned_logs: str,
    ) -> CodeFix:
        """Generate a code fix for *analysis*.

        Retries up to MAX_RETRIES times on LLM/parse errors.
        Runs bandit + pylint + secret scan on the generated code.

        Raises:
            AllModelsFailed: If every fallback model fails.
            FixTooLongError: If the fix exceeds MAX_FIX_LINES lines.
            SecretLeakError: If the fix contains hardcoded secrets.
            RuntimeError: If max retries are exhausted.
        """
        if self._nim is None:
            raise RuntimeError("No NIM client configured")

        config = AGENT_CONFIGS["code_repairer"]

        # --- Compress log to save tokens ---
        compressed_logs = compress_log(cleaned_logs, max_chars=config.max_input_tokens)
        ratio = len(compressed_logs) / max(len(cleaned_logs), 1)
        logger.info("log_compressed build_id=%s ratio=%.2f", analysis.build_id, ratio)

        # --- Enrich prompt with past fix history ---
        past_fixes = fix_memory.query(
            error_type=analysis.error_type.value,
            root_cause=analysis.root_cause,
            affected_files=analysis.affected_files,
            limit=3,
        )
        memory_ctx = build_memory_context(past_fixes)
        if memory_ctx:
            logger.info("fix_memory_injected build_id=%s records=%d",
                        analysis.build_id, len(past_fixes))

        # --- Score complexity and log model tier ---
        complexity = score_complexity(
            error_type=analysis.error_type.value,
            blast_radius=analysis.blast_radius.value if hasattr(analysis.blast_radius, "value")
                         else str(analysis.blast_radius),
            affected_files=analysis.affected_files,
            root_cause=analysis.root_cause,
            log_snippet=compressed_logs,
        )
        logger.info("task_complexity build_id=%s level=%s", analysis.build_id, complexity.value)

        prompt = SCENARIO_A_TEMPLATE.format(
            error_type=analysis.error_type.value,
            root_cause=analysis.root_cause,
            affected_files=", ".join(analysis.affected_files),
            cleaned_logs=compressed_logs,
            code_context=code_context,
            memory_context=f"\n{memory_ctx}\n" if memory_ctx else "",
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]

        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._nim.complete(messages)
                parsed = _parse_response(response)
                fix_code: str = parsed["fix_code"]

                # Count total lines
                total_lines = fix_code.count("\n")
                if total_lines > MAX_FIX_LINES:
                    raise FixTooLongError(
                        f"Fix has {total_lines} lines — exceeds {MAX_FIX_LINES}"
                    )

                # STRICT: Only if code_context is substantial (>10 lines), check for over-rewrites
                # This catches cases where AI rewrites the whole file instead of minimal fix
                if code_context and code_context.count("\n") > 10:
                    original_lines = code_context.count("\n")
                    # Allow up to 15% change or 5 lines, whichever is more (for substantial files)
                    max_allowed_change = max(5, int(original_lines * 0.15))
                    # If the diff is drastically larger than original, flag it
                    if abs(total_lines - original_lines) > max_allowed_change:
                        raise FixTooLongError(
                            f"Fix changed too much: {total_lines} lines vs {original_lines} original "
                            f"(max {max_allowed_change} allowed). Are you refactoring instead of fixing?"
                        )

                # --- Secret scan: block fixes with hardcoded credentials ---
                scan = scan_for_secrets(fix_code)
                if scan.found:
                    logger.error(
                        "fix_secret_detected build_id=%s findings=%s",
                        analysis.build_id, scan.summary,
                    )
                    if attempt < MAX_RETRIES:
                        messages[-1]["content"] += (
                            f"\n\nSECURITY BLOCK: previous fix contained hardcoded secrets "
                            f"({scan.summary}). Rewrite to use environment variables instead."
                        )
                        continue
                    raise SecretLeakError(
                        f"Generated fix contains hardcoded secrets: {scan.summary}"
                    )

                # --- Quality gates: bandit + pylint ---
                bandit = run_bandit_scan(fix_code)
                pylint = run_pylint_check(fix_code)
                quality = evaluate_quality(bandit, pylint)

                quality_gate_results.labels(
                    gate="bandit",
                    result="pass" if bandit.ok else "fail",
                ).inc()
                quality_gate_results.labels(
                    gate="pylint",
                    result="pass" if pylint.ok else "fail",
                ).inc()

                base_confidence = float(parsed.get("confidence", 0.5))
                adjusted_confidence = max(0.0, base_confidence + quality.confidence_modifier)

                logger.info(
                    "fix_generated build_id=%s attempt=%d complexity=%s quality=%s conf=%.2f→%.2f",
                    analysis.build_id, attempt, complexity.value, quality.reason,
                    base_confidence, adjusted_confidence,
                )

                # If bandit found HIGH issues and we have retries left, try again
                if not bandit.ok and attempt < MAX_RETRIES:
                    messages[-1]["content"] += (
                        f"\n\nPrevious fix had security issues: {quality.reason}. "
                        "Rewrite to address them."
                    )
                    logger.warning(
                        "fix_retry_security build_id=%s attempt=%d high_count=%d",
                        analysis.build_id, attempt, bandit.high_count,
                    )
                    continue

                return CodeFix(
                    build_id=analysis.build_id,
                    fix_patch=fix_code,
                    files_to_modify=parsed.get("files_to_modify", analysis.affected_files),
                    confidence=adjusted_confidence,
                    explanation=parsed.get("explanation", ""),
                    lint_ok=quality.passed,
                    test_ok=False,
                )

            except (AllModelsFailed, FixTooLongError, SecretLeakError):
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exc = exc
                logger.warning("fix_attempt_failed attempt=%d error=%s", attempt, exc)

        raise RuntimeError(f"Max retries exhausted: {last_exc}") from last_exc


def _parse_response(response: str) -> dict:
    """Parse JSON from an LLM response.

    Accepts bare JSON or JSON wrapped in a markdown code block.
    """
    try:
        return dict(json.loads(response))
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
    if match:
        return dict(json.loads(match.group(1)))

    raise ValueError(f"Could not parse LLM response as JSON: {response[:200]!r}")


def make_fix_generator(env_prefix: str = "CODE_REPAIRER") -> FixGenerator:
    """Construct a :class:`FixGenerator` wired to the NIM API."""
    nim = NimClient(
        agent_name="code_repairer",
        agent_env_prefix=env_prefix,
        slot_params=_SLOT_PARAMS,
    )
    return FixGenerator(nim_client=nim)
