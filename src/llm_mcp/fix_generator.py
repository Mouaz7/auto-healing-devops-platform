"""Agent 5: Fix generator — orchestrates LLM calls with quality gates.

Constraints (per spec):
  - Max 100 lines changed (surgical) / 600 (complex rewrite)
  - Max 8 retries; budget scales with bug count (up to 14 for 10+ bug files)
  - 120 s timeout per LLM call
  - Bandit + Pylint + secret scan before returning

Sibling modules (one responsibility each):
  - fix_exceptions.py    — exception types
  - fix_prompt_builder.py — prompt construction + retry budget
  - fix_code_handler.py  — extract fix code, validate length, resolve bugs_found
  - autoheal_parser.py   — AUTO-HEAL comment parsing
  - fix_validators.py    — syntax + runtime checks
  - fix_prompts.py       — retry-prompt builder
  - fix_parsers.py       — surgical patch + JSON parse
"""
from __future__ import annotations

import logging

from src.llm_mcp.fix_code_handler import (
    enforce_length_limits,
    extract_fix_code,
    resolve_bugs_found,
)
from src.llm_mcp.fix_exceptions import (
    FixStillBrokenError,
    FixTooLongError,
    NoCodeContextError,
    SecretLeakError,
    SyntaxFixExhaustedError,
)
from src.llm_mcp.fix_parsers import apply_surgical_patch, parse_response, TruncatedResponseError
from src.llm_mcp.fix_prompt_builder import build_fix_prompt, compute_attempt_budget
from src.llm_mcp.fix_prompts import build_retry_prompt, extract_bug_list
from src.llm_mcp.fix_validators import (
    clean_files,
    count_bugs_in_logs,
    count_syntax_errors,
    validate_fix_runtime,
    validate_fix_syntax,
)
from src.shared.config import AGENT_CONFIGS
from src.shared.fix_memory import build_memory_context, fix_memory
from src.shared.metrics import quality_gate_results
from src.shared.model_fallback import AllModelsFailed
from src.shared.models import CodeFix, FailureAnalysis
from src.shared.nim_client import NimClient, SlotParams
from src.shared.prompt_compressor import compress_log
from src.shared.quality_gates import evaluate_quality, run_bandit_scan, run_pylint_check
from src.shared.secret_scanner import scan_for_secrets
from src.llm_mcp.prompt_templates import COMPLEX_MODE_THRESHOLD
from src.shared.task_complexity import score_complexity

logger = logging.getLogger(__name__)

_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (0.7, 0.8, 4096),
    "FALLBACK_1": (1.0, 0.95, 8192),
    "FALLBACK_2": (1.0, 1.0, 4096),
    "FALLBACK_3": (0.6, 0.7, 4096),
}

# Backwards-compat re-exports — tests import these private names from here.
_clean_files          = clean_files
_count_syntax_errors  = count_syntax_errors
_validate_fix_syntax  = validate_fix_syntax
_validate_fix_runtime = validate_fix_runtime
_build_retry_prompt   = build_retry_prompt
_extract_bug_list     = extract_bug_list
_apply_surgical_patch = apply_surgical_patch
_parse_response       = parse_response


class FixGenerator:
    """Orchestrate LLM calls to produce a validated CodeFix."""

    def __init__(self, nim_client: NimClient | None = None) -> None:
        self._nim = nim_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate_fix(
        self,
        analysis: FailureAnalysis,
        code_context: str,
        cleaned_logs: str,
        arch_layer: str = "",
        arch_fix_hint: str = "",
    ) -> CodeFix:
        """Generate a validated code fix for *analysis*.

        Raises:
            AllModelsFailed, FixTooLongError, SecretLeakError,
            NoCodeContextError, FixStillBrokenError, SyntaxFixExhaustedError,
            RuntimeError (max retries exhausted).
        """
        if self._nim is None:
            raise RuntimeError("No NIM client configured")
        if not code_context or not code_context.strip():
            logger.error(
                "fix_generator_aborted build_id=%s reason=empty_code_context files=%s",
                analysis.build_id, analysis.affected_files,
            )
            raise NoCodeContextError(
                "Cannot generate fix: code_context is empty. "
                "Agent 4 failed to identify or fetch the source file."
            )

        config = AGENT_CONFIGS["code_repairer"]
        compressed_logs = compress_log(cleaned_logs, max_chars=config.max_input_tokens)
        logger.info(
            "log_compressed build_id=%s ratio=%.2f",
            analysis.build_id,
            len(compressed_logs) / max(len(cleaned_logs), 1),
        )

        bug_count = count_bugs_in_logs(compressed_logs)
        complex_mode = (
            bug_count >= COMPLEX_MODE_THRESHOLD
            or count_syntax_errors(code_context) > 0
        )
        if complex_mode:
            logger.info(
                "complex_mode_activated build_id=%s bugs=%d",
                analysis.build_id, bug_count,
            )

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

        complexity = score_complexity(
            error_type=analysis.error_type.value,
            blast_radius=(
                analysis.blast_radius.value
                if hasattr(analysis.blast_radius, "value")
                else str(analysis.blast_radius)
            ),
            affected_files=analysis.affected_files,
            root_cause=analysis.root_cause,
            log_snippet=compressed_logs,
        )
        logger.info(
            "task_complexity build_id=%s level=%s mode=%s",
            analysis.build_id, complexity.value,
            "complex" if complex_mode else "surgical",
        )

        if arch_fix_hint:
            memory_ctx = (
                f"\n=== ARCHITECTURE CONTEXT ===\n"
                f"Layer: {arch_layer}\nGuidance: {arch_fix_hint}\n"
            ) + (memory_ctx or "")

        prompt, system = build_fix_prompt(
            complex_mode, analysis, compressed_logs, code_context, memory_ctx, bug_count,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ]
        attempt_budget = compute_attempt_budget(bug_count)
        logger.info("retry_budget build_id=%s bugs=%d attempts=%d",
                    analysis.build_id, bug_count, attempt_budget)

        return self._retry_loop(
            messages, prompt, attempt_budget, complex_mode,
            analysis, code_context, bug_count,
        )

    # ------------------------------------------------------------------
    # Retry loop
    # ------------------------------------------------------------------

    def _retry_loop(
        self,
        messages: list[dict],
        original_user_prompt: str,
        attempt_budget: int,
        complex_mode: bool,
        analysis: FailureAnalysis,
        code_context: str,
        bug_count: int,
    ) -> CodeFix:
        last_exc: Exception = RuntimeError("No attempts made")
        failed_attempts: list[dict] = []
        budget_updated = False
        attempt = -1
        current_max_tokens: int | None = (
            AGENT_CONFIGS["code_repairer"].max_tokens_per_request * 2
            if complex_mode else None
        )

        while True:
            attempt += 1
            if attempt >= attempt_budget:
                break
            try:
                response = self._nim.complete(messages, max_tokens=current_max_tokens)
                parsed = parse_response(response)

                if not budget_updated:
                    budget_updated = True
                    llm_bc = parsed.get("bug_count")
                    if isinstance(llm_bc, int) and 1 <= llm_bc <= 50:
                        new_budget = compute_attempt_budget(llm_bc)
                        if new_budget > attempt_budget:
                            attempt_budget = new_budget
                            logger.info(
                                "attempt_budget_updated build_id=%s new=%d bug_count=%d",
                                analysis.build_id, attempt_budget, llm_bc,
                            )

                fix_code, changed_lines = extract_fix_code(
                    parsed, code_context, complex_mode, analysis,
                )

                # Syntax gate
                syntax_ok, syntax_err = validate_fix_syntax(fix_code)
                if not syntax_ok:
                    logger.warning("fix_syntax_invalid build_id=%s attempt=%d err=%s",
                                   analysis.build_id, attempt, syntax_err)
                    if attempt < attempt_budget - 1:
                        failed_attempts.append({
                            "attempt": attempt, "kind": "syntax",
                            "err": syntax_err[:1600], "fix_preview": fix_code[:1000],
                        })
                        if (sum(1 for a in failed_attempts if a["kind"] == "syntax") >= 2
                                and not complex_mode):
                            complex_mode = True
                            logger.info("complex_mode_escalated build_id=%s "
                                        "reason=repeated_syntax_errors", analysis.build_id)
                        messages[-1]["content"] = build_retry_prompt(
                            original_user_prompt, failed_attempts,
                        )
                        continue
                    raise SyntaxFixExhaustedError(
                        f"Generated fix has syntax error after {attempt_budget} "
                        f"attempts: {syntax_err}"
                    )

                # Runtime gate
                runtime_ok, runtime_err = validate_fix_runtime(fix_code)
                if not runtime_ok:
                    logger.warning("fix_runtime_invalid build_id=%s attempt=%d err=%s",
                                   analysis.build_id, attempt, runtime_err)
                    if attempt < attempt_budget - 1:
                        failed_attempts.append({
                            "attempt": attempt, "kind": "runtime",
                            "err": runtime_err[:5000], "fix_preview": fix_code[:1000],
                        })
                        messages[-1]["content"] = build_retry_prompt(
                            original_user_prompt, failed_attempts,
                        )
                        continue
                    raise FixStillBrokenError(
                        f"AI tried {attempt_budget} times but the fix still does not work: "
                        f"{runtime_err}. Manual review required."
                    )

                # Length gate
                enforce_length_limits(fix_code, code_context, complex_mode, changed_lines)

                # Secret scan
                scan = scan_for_secrets(fix_code)
                if scan.found:
                    logger.error("fix_secret_detected build_id=%s findings=%s",
                                 analysis.build_id, scan.summary)
                    if attempt < attempt_budget - 1:
                        messages[-1]["content"] += (
                            f"\n\nSECURITY BLOCK: fix contained hardcoded secrets "
                            f"({scan.summary}). Use environment variables instead."
                        )
                        continue
                    raise SecretLeakError(
                        f"Generated fix contains hardcoded secrets: {scan.summary}"
                    )

                # Quality gates
                bandit = run_bandit_scan(fix_code)
                pylint = run_pylint_check(fix_code)
                quality = evaluate_quality(bandit, pylint)
                quality_gate_results.labels(
                    gate="bandit", result="pass" if bandit.ok else "fail",
                ).inc()
                quality_gate_results.labels(
                    gate="pylint", result="pass" if pylint.ok else "fail",
                ).inc()

                base_confidence = float(parsed.get("confidence", 0.5))
                adjusted_confidence = max(0.0, base_confidence + quality.confidence_modifier)
                logger.info(
                    "fix_generated build_id=%s attempt=%d mode=%s bugs=%d "
                    "quality=%s conf=%.2f→%.2f",
                    analysis.build_id, attempt,
                    "complex" if complex_mode else "surgical",
                    bug_count, quality.reason, base_confidence, adjusted_confidence,
                )

                if not bandit.ok and attempt < attempt_budget - 1:
                    messages[-1]["content"] += (
                        f"\n\nPrevious fix had security issues: {quality.reason}. "
                        "Rewrite to address them."
                    )
                    logger.warning("fix_retry_security build_id=%s attempt=%d",
                                   analysis.build_id, attempt)
                    continue

                bugs_found = resolve_bugs_found(parsed, fix_code, changed_lines, code_context)
                llm_files = clean_files(parsed.get("files_to_modify", []))
                final_files = analysis.affected_files or llm_files
                if not final_files:
                    logger.warning("fix_has_no_valid_files build_id=%s llm_raw=%s",
                                   analysis.build_id, parsed.get("files_to_modify"))

                return CodeFix(
                    build_id=analysis.build_id,
                    fix_patch=fix_code,
                    files_to_modify=final_files,
                    confidence=adjusted_confidence,
                    explanation=parsed.get("explanation", ""),
                    lint_ok=quality.passed,
                    test_ok=False,
                    changed_lines={str(k): v for k, v in changed_lines.items()},
                    bugs_found=bugs_found,
                    model_used=getattr(self._nim, "last_model", "") if self._nim else "",
                    regression_risk=parsed.get("regression_risk", ""),
                    test_hints=parsed.get("test_hints", []),
                )

            except TruncatedResponseError as exc:
                last_exc = exc
                config = AGENT_CONFIGS["code_repairer"]
                current_max_tokens = min(
                    (current_max_tokens or config.max_tokens_per_request) * 2,
                    16_000,
                )
                logger.warning(
                    "fix_truncated build_id=%s attempt=%d — bumping tokens to %d",
                    analysis.build_id, attempt, current_max_tokens,
                )
            except (AllModelsFailed, FixTooLongError, SecretLeakError,
                    NoCodeContextError, FixStillBrokenError, SyntaxFixExhaustedError):
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exc = exc
                logger.warning("fix_attempt_failed attempt=%d error=%s", attempt, exc)

        raise RuntimeError(
            f"Max retries exhausted after {attempt_budget} attempts: {last_exc}"
        ) from last_exc


def make_fix_generator(env_prefix: str = "CODE_REPAIRER") -> FixGenerator:
    """Construct a :class:`FixGenerator` wired to the NIM API."""
    nim = NimClient(
        agent_name="code_repairer",
        agent_env_prefix=env_prefix,
        slot_params=_SLOT_PARAMS,
    )
    return FixGenerator(nim_client=nim)
