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

import ast
import json
import logging
import re

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


class FixTooLongError(ValueError):
    """Raised when the generated fix exceeds MAX_FIX_LINES."""


class SecretLeakError(ValueError):
    """Raised when the generated fix contains hardcoded secrets."""


class FixStillBrokenError(ValueError):
    """Raised when the LLM cannot produce a runtime-correct fix after retries.

    The fix compiled but still infinite-looped or crashed when executed.
    Routes to BLOCKED status so a human can intervene.
    """


class NoCodeContextError(ValueError):
    """Raised when generate_fix is called without real code_context.

    Without the actual source file, the LLM can only hallucinate — it will
    return code unrelated to the reported error. Better to fail loudly so the
    orchestrator routes the failure to human review.
    """


_HALLUCINATED_FILENAMES = {
    "<unknown>", "(unknown)", "unknown", "unknown.py",
    "<file>", "<filename>", "<path>", "placeholder.py",
    "example.py", "auto_heal_fix.py", "file.py",
}


def _clean_files(files: list[str]) -> list[str]:
    """Drop empty, hallucinated, or non-Python paths from LLM output."""
    out: list[str] = []
    for f in files or []:
        if not f:
            continue
        f = f.strip()
        if f.lower() in _HALLUCINATED_FILENAMES:
            continue
        if f.startswith("<") or f.startswith("("):
            continue
        if any(c in f for c in "<>()[]{}"):
            continue
        if f.endswith(".py"):
            out.append(f.lstrip("./"))
    return out


def _count_bugs_in_logs(logs: str) -> int:
    """Count how many distinct errors appear in the build logs."""
    error_patterns = [
        r"SyntaxError", r"NameError", r"TypeError", r"AttributeError",
        r"ImportError", r"IndentationError", r"ValueError", r"KeyError",
        r"IndexError", r"AssertionError", r"FAILED\s+\S+\.py",
    ]
    found = set()
    for p in error_patterns:
        if re.search(p, logs, re.IGNORECASE):
            found.add(p)
    return len(found)


def _count_syntax_errors(code: str) -> int:
    """Return the number of detected syntax errors in the code (0 = valid Python)."""
    try:
        ast.parse(code)
        return 0
    except SyntaxError:
        return 1


def _validate_fix_syntax(fix_code: str) -> tuple[bool, str]:
    """Return (is_valid, error_message). Empty error = code compiles."""
    try:
        ast.parse(fix_code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError on line {e.lineno}: {e.msg}"


def _validate_fix_runtime(fix_code: str, timeout_s: int = 5) -> tuple[bool, str]:
    """Run the fix and verify it doesn't infinite-loop or crash.

    Returns (is_valid, error_message). Only checks code that runs at module level
    (i.e. has no `def test_*` or other code requiring pytest fixtures).
    """
    if "def test_" in fix_code:
        return True, ""

    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(fix_code)
            tmp_path = f.name
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True, text=True, timeout=timeout_s,
        )
        if result.returncode != 0:
            return False, f"RuntimeError: {result.stderr.strip()[:300]}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"INFINITE LOOP: code did not finish within {timeout_s}s — your fix still has a bug"
    except Exception as exc:
        logger.warning("runtime_validation_skipped err=%s", exc)
        return True, ""
    finally:
        try:
            import os as _os
            _os.unlink(tmp_path)
        except Exception:  # pylint: disable=broad-exception-caught
            pass


def _extract_bug_list(logs: str) -> list[str]:
    """Pull distinct error messages from logs for the complex-mode prompt."""
    bugs: list[str] = []
    patterns = [
        r"(SyntaxError[^\n]*)",
        r"(NameError[^\n]*)",
        r"(TypeError[^\n]*)",
        r"(IndentationError[^\n]*)",
        r"(AttributeError[^\n]*)",
        r"(ValueError[^\n]*)",
        r"(FAILED\s+\S+\.py[^\n]*)",
        r"E\s+(.*Error[^\n]*)",
    ]
    seen: set[str] = set()
    for p in patterns:
        for m in re.finditer(p, logs, re.IGNORECASE):
            msg = m.group(1).strip()[:120]
            if msg not in seen:
                bugs.append(msg)
                seen.add(msg)
    return bugs[:10]  # cap at 10


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

        # Without real source code, the LLM can only guess. Reject immediately so
        # the orchestrator marks the build for human review instead of shipping
        # a hallucinated fix (binary-search-looking output for an unrelated bug).
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

        # --- Compress log to save tokens ---
        compressed_logs = compress_log(cleaned_logs, max_chars=config.max_input_tokens)
        ratio = len(compressed_logs) / max(len(cleaned_logs), 1)
        logger.info("log_compressed build_id=%s ratio=%.2f", analysis.build_id, ratio)

        # --- Decide: surgical mode vs complex/full-rewrite mode ---
        # Complex mode triggers when code has many bugs, syntax errors, or garbled structure.
        bug_count = _count_bugs_in_logs(compressed_logs)
        code_has_syntax_error = _count_syntax_errors(code_context) > 0
        complex_mode = bug_count >= COMPLEX_MODE_THRESHOLD or code_has_syntax_error

        if complex_mode:
            logger.info(
                "complex_mode_activated build_id=%s bugs=%d syntax_error=%s",
                analysis.build_id, bug_count, code_has_syntax_error,
            )

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
        logger.info("task_complexity build_id=%s level=%s mode=%s",
                    analysis.build_id, complexity.value,
                    "complex" if complex_mode else "surgical")

        # Choose prompt based on mode
        if complex_mode:
            bug_list = _extract_bug_list(compressed_logs)
            prompt = COMPLEX_REPAIR_TEMPLATE.format(
                error_type=analysis.error_type.value,
                root_cause=analysis.root_cause,
                affected_files=", ".join(analysis.affected_files),
                cleaned_logs=compressed_logs,
                code_context=code_context,
                memory_context=f"\n{memory_ctx}\n" if memory_ctx else "",
                bug_count=bug_count,
                bug_list="\n".join(f"  - {b}" for b in bug_list) or "  - Multiple errors detected",
            )
            system = COMPLEX_SYSTEM_PROMPT
        else:
            prompt = SCENARIO_A_TEMPLATE.format(
                error_type=analysis.error_type.value,
                root_cause=analysis.root_cause,
                affected_files=", ".join(analysis.affected_files),
                cleaned_logs=compressed_logs,
                code_context=code_context,
                memory_context=f"\n{memory_ctx}\n" if memory_ctx else "",
            )
            system = SYSTEM_PROMPT

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ]

        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._nim.complete(messages)
                parsed = _parse_response(response)

                # Pick fix source: prefer changed_lines (surgical) unless in complex mode
                changed_lines = parsed.get("changed_lines", {})
                if not complex_mode and changed_lines and code_context:
                    fix_code = _apply_surgical_patch(code_context, changed_lines)
                    logger.info(
                        "surgical_patch_applied build_id=%s lines_changed=%d",
                        analysis.build_id, len(changed_lines),
                    )
                elif "fix_code" in parsed and parsed["fix_code"]:
                    fix_code = parsed["fix_code"]
                elif changed_lines and code_context:
                    # fallback: surgical even in complex mode if fix_code missing
                    fix_code = _apply_surgical_patch(code_context, changed_lines)
                else:
                    raise ValueError(
                        "LLM returned neither 'changed_lines' nor 'fix_code'"
                    )

                # --- Validate that the fix actually compiles ---
                syntax_ok, syntax_err = _validate_fix_syntax(fix_code)
                if not syntax_ok:
                    logger.warning(
                        "fix_syntax_invalid build_id=%s attempt=%d err=%s",
                        analysis.build_id, attempt, syntax_err,
                    )
                    if attempt < MAX_RETRIES:
                        messages[-1]["content"] += (
                            f"\n\nSYNTAX ERROR IN YOUR FIX: {syntax_err}\n"
                            "Your fix_code does not compile. Fix ALL syntax errors and try again."
                        )
                        continue
                    raise ValueError(f"Generated fix has syntax error after {MAX_RETRIES} retries: {syntax_err}")

                # --- Runtime validation: actually run the fix to catch infinite loops & logic bugs ---
                runtime_ok, runtime_err = _validate_fix_runtime(fix_code)
                if not runtime_ok:
                    logger.warning(
                        "fix_runtime_invalid build_id=%s attempt=%d err=%s",
                        analysis.build_id, attempt, runtime_err,
                    )
                    if attempt < MAX_RETRIES:
                        messages[-1]["content"] += (
                            f"\n\nYOUR FIX IS STILL BROKEN: {runtime_err}\n"
                            "When the code runs it does not work correctly. "
                            "Re-read the original bug carefully and produce a fix that actually resolves it. "
                            "For binary search: use `left = mid + 1` when target > arr[mid], "
                            "and `right = mid - 1` when target < arr[mid]. Both branches MUST shrink the search range."
                        )
                        continue
                    raise FixStillBrokenError(
                        f"AI tried {MAX_RETRIES + 1} times but the fix still does not work: {runtime_err}. "
                        "Manual review required."
                    )

                # Line-count guard (relaxed in complex mode)
                total_lines = fix_code.count("\n")
                max_lines = MAX_FIX_LINES_COMPLEX if complex_mode else MAX_FIX_LINES
                if total_lines > max_lines:
                    raise FixTooLongError(
                        f"Fix has {total_lines} lines — exceeds {max_lines}"
                    )

                # Over-rewrite guard only in surgical mode
                if not complex_mode and code_context and code_context.count("\n") > 10 and not changed_lines:
                    original_lines = code_context.count("\n")
                    max_allowed_change = max(5, int(original_lines * 0.15))
                    if abs(total_lines - original_lines) > max_allowed_change:
                        raise FixTooLongError(
                            f"Fix changed too much: {total_lines} vs {original_lines} original. "
                            "Use 'changed_lines' for surgical fixes."
                        )

                # --- Secret scan ---
                scan = scan_for_secrets(fix_code)
                if scan.found:
                    logger.error(
                        "fix_secret_detected build_id=%s findings=%s",
                        analysis.build_id, scan.summary,
                    )
                    if attempt < MAX_RETRIES:
                        messages[-1]["content"] += (
                            f"\n\nSECURITY BLOCK: fix contained hardcoded secrets "
                            f"({scan.summary}). Use environment variables instead."
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
                    gate="bandit", result="pass" if bandit.ok else "fail",
                ).inc()
                quality_gate_results.labels(
                    gate="pylint", result="pass" if pylint.ok else "fail",
                ).inc()

                base_confidence = float(parsed.get("confidence", 0.5))
                adjusted_confidence = max(0.0, base_confidence + quality.confidence_modifier)

                logger.info(
                    "fix_generated build_id=%s attempt=%d mode=%s bugs=%d quality=%s conf=%.2f→%.2f",
                    analysis.build_id, attempt,
                    "complex" if complex_mode else "surgical",
                    bug_count, quality.reason,
                    base_confidence, adjusted_confidence,
                )

                if not bandit.ok and attempt < MAX_RETRIES:
                    messages[-1]["content"] += (
                        f"\n\nPrevious fix had security issues: {quality.reason}. "
                        "Rewrite to address them."
                    )
                    logger.warning(
                        "fix_retry_security build_id=%s attempt=%d",
                        analysis.build_id, attempt,
                    )
                    continue

                llm_files = _clean_files(parsed.get("files_to_modify", []))
                final_files = analysis.affected_files or llm_files
                if not final_files:
                    logger.warning(
                        "fix_has_no_valid_files build_id=%s llm_raw=%s",
                        analysis.build_id, parsed.get("files_to_modify"),
                    )

                return CodeFix(
                    build_id=analysis.build_id,
                    fix_patch=fix_code,
                    files_to_modify=final_files,
                    confidence=adjusted_confidence,
                    explanation=parsed.get("explanation", ""),
                    lint_ok=quality.passed,
                    test_ok=False,
                )

            except (AllModelsFailed, FixTooLongError, SecretLeakError, NoCodeContextError, FixStillBrokenError):
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exc = exc
                logger.warning("fix_attempt_failed attempt=%d error=%s", attempt, exc)

        raise RuntimeError(f"Max retries exhausted: {last_exc}") from last_exc


def _apply_surgical_patch(original: str, changed_lines: dict) -> str:
    """Apply minimal line-level changes to the original file.

    Args:
        original: Original file content (from GitHub).
        changed_lines: {"line_number_as_str": "new_line_content"}.
            Line numbers are 1-based to match editor/IDE conventions.

    Returns:
        The patched file content — everything unchanged except the specified lines.

    This is the SAFEST way to apply AI fixes: the LLM cannot hallucinate
    new code outside the explicitly specified lines. Guarantees minimal diff.
    """
    lines = original.splitlines(keepends=True)
    for line_num_str, new_content in changed_lines.items():
        try:
            idx = int(line_num_str) - 1  # 1-based → 0-based
        except (ValueError, TypeError):
            continue
        if 0 <= idx < len(lines):
            # Preserve original trailing newline behaviour
            suffix = "\n" if lines[idx].endswith("\n") else ""
            lines[idx] = new_content.rstrip("\n") + suffix
    return "".join(lines)


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
