"""Agent 5: Fix generator — produces code fixes via NIM LLM with quality checks.

Constraints (per spec):
  - Max 50 lines of changed code
  - Max 2 retries on LLM failure
  - 60 s timeout (enforced by NimClient via AgentModelConfig.timeout_seconds)
  - Bandit + Pylint run on generated code before returning
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
from src.shared.metrics import quality_gate_results
from src.shared.model_fallback import AllModelsFailed
from src.shared.models import CodeFix, FailureAnalysis
from src.shared.nim_client import NimClient, SlotParams
from src.shared.quality_gates import (
    run_bandit_scan,
    run_pylint_check,
    evaluate_quality,
)

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
        Runs bandit + pylint on the generated code.

        Raises:
            AllModelsFailed: If every fallback model fails.
            FixTooLongError: If the fix exceeds MAX_FIX_LINES lines.
            RuntimeError: If max retries are exhausted.
        """
        if self._nim is None:
            raise RuntimeError("No NIM client configured")

        config = AGENT_CONFIGS["code_repairer"]

        prompt = SCENARIO_A_TEMPLATE.format(
            error_type=analysis.error_type.value,
            root_cause=analysis.root_cause,
            affected_files=", ".join(analysis.affected_files),
            cleaned_logs=cleaned_logs[:config.max_input_tokens],
            code_context=code_context,
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

                if fix_code.count("\n") > MAX_FIX_LINES:
                    raise FixTooLongError(
                        f"Fix has {fix_code.count(chr(10))} lines — exceeds {MAX_FIX_LINES}"
                    )

                # Run quality gates on generated code
                bandit = run_bandit_scan(fix_code)
                pylint = run_pylint_check(fix_code)
                quality = evaluate_quality(bandit, pylint)

                # Track quality gate results
                quality_gate_results.labels(
                    gate="bandit",
                    result="pass" if bandit.ok else "fail",
                ).inc()
                quality_gate_results.labels(
                    gate="pylint",
                    result="pass" if pylint.ok else "fail",
                ).inc()

                # Adjust confidence based on quality
                base_confidence = float(parsed.get("confidence", 0.5))
                adjusted_confidence = max(0.0, base_confidence + quality.confidence_modifier)

                logger.info(
                    "fix_generated build_id=%s attempt=%d quality=%s conf=%.2f→%.2f",
                    analysis.build_id, attempt, quality.reason,
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
                    test_ok=False,   # test execution is Sprint 6 concern
                )

            except (AllModelsFailed, FixTooLongError):
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exc = exc
                logger.warning("fix_attempt_failed attempt=%d error=%s", attempt, exc)

        raise RuntimeError(f"Max retries exhausted: {last_exc}") from last_exc


def _parse_response(response: str) -> dict:
    """Parse JSON from an LLM response.

    Accepts bare JSON or JSON wrapped in a markdown code block.
    """
    # Try bare JSON first
    try:
        return dict(json.loads(response))
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` or ``` ... ``` block
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
