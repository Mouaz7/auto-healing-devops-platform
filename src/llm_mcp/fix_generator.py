"""Agent 5: Fix generator — produces code fixes via NIM LLM with quality checks.

Constraints (per spec):
  - Max 100 lines changed (surgical) / 600 (complex rewrite)
  - Rejects fixes that refactor or change unrelated code
  - Max 8 retries on LLM failure (9 attempts total); attempt budget scales
    with bug count up to 14 attempts for 10+ bug files
  - 120 s timeout per LLM call
  - Bandit + Pylint + secret scan run on generated code before returning

Helpers live in sibling modules to keep this file focused on the loop:
  - fix_validators.py — syntax + runtime checks
  - fix_prompts.py    — retry-prompt builder
  - fix_parsers.py    — surgical patch + JSON parse
"""
from __future__ import annotations

import logging

from src.llm_mcp.bug_scanner import BugPatternScanner
from src.llm_mcp.fix_parsers import apply_surgical_patch, parse_response
from src.llm_mcp.fix_prompts import build_retry_prompt, extract_bug_list
from src.llm_mcp.fix_validators import (
    clean_files,
    count_bugs_in_logs,
    count_syntax_errors,
    validate_fix_runtime,
    validate_fix_syntax,
)
from src.llm_mcp.prompt_templates import (
    COMPLEX_MODE_THRESHOLD,
    COMPLEX_REPAIR_TEMPLATE,
    COMPLEX_SYSTEM_PROMPT,
    MAX_FIX_LINES,
    MAX_FIX_LINES_COMPLEX,
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


# --- Exceptions -------------------------------------------------------

class FixTooLongError(ValueError):
    """Raised when the generated fix exceeds MAX_FIX_LINES."""


class SecretLeakError(ValueError):
    """Raised when the generated fix contains hardcoded secrets."""


class FixStillBrokenError(ValueError):
    """LLM cannot produce a runtime-correct fix after retries.

    The fix compiled but still infinite-looped or crashed when executed.
    Routes to BLOCKED so a human can intervene.
    """


class NoCodeContextError(ValueError):
    """generate_fix called without real code_context.

    Without the actual source file, the LLM can only hallucinate. Better to
    fail loudly so the orchestrator routes the failure to human review.
    """


class SyntaxFixExhaustedError(ValueError):
    """Every retry produced fix_code that fails to compile.

    Treated as BLOCKED (HTTP 422), not 503 — more retries from the
    orchestrator will not help; the LLM kept producing invalid Python.
    """


# --- Backwards-compat re-exports for tests / old imports --------------
# Tests historically import these private names from this module. The real
# implementations now live in sibling modules; these aliases keep imports
# stable without forcing every test to update.
_clean_files = clean_files
_count_bugs_in_logs = count_bugs_in_logs
_count_syntax_errors = count_syntax_errors
_validate_fix_syntax = validate_fix_syntax
_validate_fix_runtime = validate_fix_runtime
_build_retry_prompt = build_retry_prompt
_extract_bug_list = extract_bug_list
_apply_surgical_patch = apply_surgical_patch
_parse_response = parse_response


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

        Retries up to MAX_RETRIES times on LLM/parse errors. Runs bandit +
        pylint + secret scan on the generated code.

        Raises:
            AllModelsFailed: every fallback model failed.
            FixTooLongError: fix exceeds MAX_FIX_LINES.
            SecretLeakError: fix contains hardcoded secrets.
            NoCodeContextError: code_context was empty (would be a hallucination).
            FixStillBrokenError: fix compiles but still misbehaves at runtime.
            SyntaxFixExhaustedError: every retry produced uncompilable code.
            RuntimeError: max retries exhausted for other reasons.
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
        ratio = len(compressed_logs) / max(len(cleaned_logs), 1)
        logger.info("log_compressed build_id=%s ratio=%.2f", analysis.build_id, ratio)

        bug_count = count_bugs_in_logs(compressed_logs)
        code_has_syntax_error = count_syntax_errors(code_context) > 0
        complex_mode = bug_count >= COMPLEX_MODE_THRESHOLD or code_has_syntax_error

        if complex_mode:
            logger.info(
                "complex_mode_activated build_id=%s bugs=%d syntax_error=%s",
                analysis.build_id, bug_count, code_has_syntax_error,
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
            blast_radius=analysis.blast_radius.value
                         if hasattr(analysis.blast_radius, "value")
                         else str(analysis.blast_radius),
            affected_files=analysis.affected_files,
            root_cause=analysis.root_cause,
            log_snippet=compressed_logs,
        )
        logger.info("task_complexity build_id=%s level=%s mode=%s",
                    analysis.build_id, complexity.value,
                    "complex" if complex_mode else "surgical")

        prompt, system = self._build_prompt(
            complex_mode, analysis, compressed_logs, code_context, memory_ctx, bug_count,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ]

        attempt_budget = self._compute_attempt_budget(bug_count)
        logger.info("retry_budget build_id=%s bugs=%d attempts=%d",
                    analysis.build_id, bug_count, attempt_budget)

        return self._retry_loop(
            messages, prompt, attempt_budget, complex_mode,
            analysis, code_context, bug_count,
        )

    # --- Prompt + budget helpers --------------------------------------

    @staticmethod
    def _build_prompt(
        complex_mode: bool,
        analysis: FailureAnalysis,
        compressed_logs: str,
        code_context: str,
        memory_ctx: str,
        bug_count: int,
    ) -> tuple[str, str]:
        """Pick the prompt template + system message for this run."""
        memory_block = f"\n{memory_ctx}\n" if memory_ctx else ""
        scan_block = BugPatternScanner.scan(code_context).to_prompt_block()
        annotated_context = scan_block + code_context if scan_block else code_context
        if complex_mode:
            bug_list = extract_bug_list(compressed_logs)
            prompt = COMPLEX_REPAIR_TEMPLATE.format(
                error_type=analysis.error_type.value,
                root_cause=analysis.root_cause,
                affected_files=", ".join(analysis.affected_files),
                cleaned_logs=compressed_logs,
                code_context=annotated_context,
                memory_context=memory_block,
                bug_count=bug_count,
                bug_list="\n".join(f"  - {b}" for b in bug_list)
                         or "  - Multiple errors detected",
            )
            return prompt, COMPLEX_SYSTEM_PROMPT

        prompt = SCENARIO_A_TEMPLATE.format(
            error_type=analysis.error_type.value,
            root_cause=analysis.root_cause,
            affected_files=", ".join(analysis.affected_files),
            cleaned_logs=compressed_logs,
            code_context=annotated_context,
            memory_context=memory_block,
        )
        return prompt, SYSTEM_PROMPT

    @staticmethod
    def _compute_attempt_budget(bug_count: int) -> int:
        """Scale retries with bug density.

        ≤2 bugs: 6 attempts.  3–9: MAX_RETRIES + 2.  10–40: MAX_RETRIES + 6.
        High-bug files need room to converge; simple 1-bug fixes don't waste calls.
        """
        if bug_count >= 10:
            return MAX_RETRIES + 6
        if bug_count >= 3:
            return MAX_RETRIES + 2
        return 6

    # --- Retry loop ---------------------------------------------------

    def _retry_loop(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
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

        for attempt in range(attempt_budget):
            try:
                response = self._nim.complete(messages)
                parsed = parse_response(response)

                fix_code, changed_lines = self._extract_fix_code(
                    parsed, code_context, complex_mode, analysis,
                )

                # --- Syntax gate ---
                syntax_ok, syntax_err = validate_fix_syntax(fix_code)
                if not syntax_ok:
                    logger.warning("fix_syntax_invalid build_id=%s attempt=%d err=%s",
                                   analysis.build_id, attempt, syntax_err)
                    if attempt < attempt_budget - 1:
                        failed_attempts.append({
                            "attempt": attempt, "kind": "syntax",
                            "err": syntax_err[:1600],
                            "fix_preview": fix_code[:1000],
                        })
                        # Two syntax errors in a row → surgical patches are
                        # mangling structure. Switch to complex_mode so the LLM
                        # rewrites the whole file instead of editing lines.
                        syntax_fail_count = sum(
                            1 for a in failed_attempts if a["kind"] == "syntax"
                        )
                        if syntax_fail_count >= 2 and not complex_mode:
                            complex_mode = True
                            logger.info(
                                "complex_mode_escalated build_id=%s "
                                "reason=repeated_syntax_errors",
                                analysis.build_id,
                            )
                        messages[-1]["content"] = build_retry_prompt(
                            original_user_prompt, failed_attempts,
                        )
                        continue
                    raise SyntaxFixExhaustedError(
                        f"Generated fix has syntax error after {attempt_budget} "
                        f"attempts: {syntax_err}"
                    )

                # --- Runtime gate ---
                runtime_ok, runtime_err = validate_fix_runtime(fix_code)
                if not runtime_ok:
                    logger.warning("fix_runtime_invalid build_id=%s attempt=%d err=%s",
                                   analysis.build_id, attempt, runtime_err)
                    if attempt < attempt_budget - 1:
                        failed_attempts.append({
                            "attempt": attempt, "kind": "runtime",
                            "err": runtime_err[:5000],
                            "fix_preview": fix_code[:1000],
                        })
                        messages[-1]["content"] = build_retry_prompt(
                            original_user_prompt, failed_attempts,
                        )
                        continue
                    raise FixStillBrokenError(
                        f"AI tried {attempt_budget} times but the fix still does not work: "
                        f"{runtime_err}. Manual review required."
                    )

                # --- Length gates ---
                self._enforce_length_limits(
                    fix_code, code_context, complex_mode, changed_lines,
                )

                # --- Secret scan ---
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

                # --- Quality gates ---
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
                    bug_count, quality.reason,
                    base_confidence, adjusted_confidence,
                )

                if not bandit.ok and attempt < attempt_budget - 1:
                    messages[-1]["content"] += (
                        f"\n\nPrevious fix had security issues: {quality.reason}. "
                        "Rewrite to address them."
                    )
                    logger.warning("fix_retry_security build_id=%s attempt=%d",
                                   analysis.build_id, attempt)
                    continue

                llm_files = clean_files(parsed.get("files_to_modify", []))
                final_files = analysis.affected_files or llm_files
                if not final_files:
                    logger.warning("fix_has_no_valid_files build_id=%s llm_raw=%s",
                                   analysis.build_id, parsed.get("files_to_modify"))

                bugs_found = parsed.get("bugs_found", [])
                explanation_text = parsed.get("explanation", "")

                # Tier 0: always parse AUTO-HEAL comments from fix_code.
                # These are the most accurate descriptions — the LLM writes them
                # inline on every changed line. They replace generic LLM bugs_found
                # (e.g. repeated "SyntaxError: expected ':'" messages) when present.
                if fix_code and not changed_lines:
                    import re as _re0
                    _autoheal_pattern = _re0.compile(r"#\s*AUTO-HEAL:\s*(.+)")
                    _autoheal_bugs: list[str] = []
                    _autoheal_lines: dict[str, str] = {}
                    for lineno, line in enumerate(fix_code.splitlines(), 1):
                        m = _autoheal_pattern.search(line)
                        if m:
                            desc = m.group(1).strip()
                            _autoheal_lines[str(lineno)] = line.rstrip()
                            _autoheal_bugs.append(f"Line {lineno}: {desc[:160]}")
                    if _autoheal_bugs:
                        # AUTO-HEAL descriptions are always preferred over generic
                        # LLM bugs_found (e.g. repeated SyntaxError messages).
                        bugs_found   = _autoheal_bugs
                        changed_lines = _autoheal_lines

                # Tier 1 fallback: synthesize from changed_lines (surgical mode).
                # Each changed line is one bug; use its AUTO-HEAL inline comment as desc.
                if not bugs_found and changed_lines:
                    for lineno_str, new_code in sorted(
                        changed_lines.items(),
                        key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
                    ):
                        comment = ""
                        if "# AUTO-HEAL:" in new_code:
                            comment = new_code.split("# AUTO-HEAL:", 1)[1].strip()
                        if comment:
                            bugs_found.append(f"Line {lineno_str}: {comment[:120]}")
                        else:
                            bugs_found.append(
                                f"Line {lineno_str}: fixed → `{new_code.strip()[:80]}`"
                            )

                # Tier 2 fallback: static AST scanner on original code (full-rewrite mode).
                # BugPatternScanner fails on files with syntax errors, so only use findings
                # when it actually returns something.
                if not bugs_found and code_context:
                    scan_result = BugPatternScanner.scan(code_context)
                    if scan_result.findings:
                        bugs_found = [
                            f"Line {f.line}: [{f.pattern}] {f.message} — {f.suggestion}"
                            for f in scan_result.findings
                        ]

                # Tier 3 fallback: parse the explanation for Phase 2 bug list.
                # LLM explanation always narrates bugs in "Phase 2: ..." section.
                # Extract numbered items like "1. missing colon" or "Bug 1: ...".
                if not bugs_found and explanation_text:
                    import re as _re
                    # Find numbered items: "1. ...", "1) ...", "Bug 1: ...", "- ..."
                    items = _re.findall(
                        r"(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•]\s*|Bug\s+\d+:\s*)(.{10,120})",
                        explanation_text,
                    )
                    if items:
                        bugs_found = [item.strip() for item in items[:20]]
                    else:
                        # Last resort: extract "N bugs" count from explanation and make
                        # generic entries so the PR shows a real number, not 0.
                        count_m = _re.search(
                            r"(\d+)\s+bugs?\b", explanation_text, _re.IGNORECASE
                        )
                        if count_m:
                            n = int(count_m.group(1))
                            bugs_found = [
                                f"Bug {i}: identified in full rewrite — see explanation"
                                for i in range(1, n + 1)
                            ]

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
                )

            except (AllModelsFailed, FixTooLongError, SecretLeakError,
                    NoCodeContextError, FixStillBrokenError,
                    SyntaxFixExhaustedError):
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exc = exc
                logger.warning("fix_attempt_failed attempt=%d error=%s", attempt, exc)

        raise RuntimeError(f"Max retries exhausted: {last_exc}") from last_exc

    # --- Per-attempt sub-helpers --------------------------------------

    @staticmethod
    def _extract_fix_code(
        parsed: dict,
        code_context: str,
        complex_mode: bool,
        analysis: FailureAnalysis,
    ) -> tuple[str, dict]:
        """Pick fix source: surgical (changed_lines) or full rewrite (fix_code)."""
        changed_lines = parsed.get("changed_lines", {})
        if not complex_mode and changed_lines and code_context:
            fix_code = apply_surgical_patch(code_context, changed_lines)
            logger.info(
                "surgical_patch_applied build_id=%s lines_changed=%d",
                analysis.build_id, len(changed_lines),
            )
        elif "fix_code" in parsed and parsed["fix_code"]:
            fix_code = parsed["fix_code"]
        elif changed_lines and code_context:
            # fallback: surgical even in complex mode if fix_code missing
            fix_code = apply_surgical_patch(code_context, changed_lines)
        else:
            raise ValueError("LLM returned neither 'changed_lines' nor 'fix_code'")
        return fix_code, changed_lines

    @staticmethod
    def _enforce_length_limits(
        fix_code: str, code_context: str, complex_mode: bool, changed_lines: dict,
    ) -> None:
        """Reject fixes that exceed MAX_FIX_LINES or rewrite too much."""
        total_lines = fix_code.count("\n")
        max_lines = MAX_FIX_LINES_COMPLEX if complex_mode else MAX_FIX_LINES
        if total_lines > max_lines:
            raise FixTooLongError(
                f"Fix has {total_lines} lines — exceeds {max_lines}"
            )
        # Over-rewrite guard only in surgical mode
        if (not complex_mode and code_context
                and code_context.count("\n") > 10 and not changed_lines):
            original_lines = code_context.count("\n")
            max_allowed_change = max(5, int(original_lines * 0.15))
            if abs(total_lines - original_lines) > max_allowed_change:
                raise FixTooLongError(
                    f"Fix changed too much: {total_lines} vs {original_lines} original. "
                    "Use 'changed_lines' for surgical fixes."
                )


def make_fix_generator(env_prefix: str = "CODE_REPAIRER") -> FixGenerator:
    """Construct a :class:`FixGenerator` wired to the NIM API."""
    nim = NimClient(
        agent_name="code_repairer",
        agent_env_prefix=env_prefix,
        slot_params=_SLOT_PARAMS,
    )
    return FixGenerator(nim_client=nim)
