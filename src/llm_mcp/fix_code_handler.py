"""Fix-code extraction, length validation, and bug-list resolution.

Answers the question: "How do I process the LLM's JSON response?"

Public API:
  - extract_fix_code()    — pick surgical patch vs full rewrite from parsed JSON
  - enforce_length_limits() — reject fixes that are too long or rewrote too much
  - resolve_bugs_found()  — build the final bugs_found list via tier hierarchy
"""
from __future__ import annotations

import logging

from src.llm_mcp.autoheal_parser import (
    collect_autoheal_bugs,
    collect_changed_line_bugs,
    llm_bugs_meaningful,
)
from src.llm_mcp.fix_exceptions import FixTooLongError
from src.llm_mcp.fix_parsers import apply_surgical_patch
from src.llm_mcp.prompt_templates import MAX_FIX_LINES, MAX_FIX_LINES_COMPLEX
from src.shared.models import FailureAnalysis

logger = logging.getLogger(__name__)


def extract_fix_code(
    parsed: dict,
    code_context: str,
    complex_mode: bool,
    analysis: FailureAnalysis,
) -> tuple[str, dict]:
    """Return (fix_code, changed_lines) from a parsed LLM JSON response.

    Preference order:
      1. Surgical patch  — changed_lines dict applied to code_context (non-complex)
      2. Full rewrite    — fix_code string from the response
      3. Surgical patch  — fallback even in complex mode if fix_code is missing
    Raises ValueError when neither field is present.
    """
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
        fix_code = apply_surgical_patch(code_context, changed_lines)
    else:
        raise ValueError("LLM returned neither 'changed_lines' nor 'fix_code'")
    return fix_code, changed_lines


def enforce_length_limits(
    fix_code: str,
    code_context: str,
    complex_mode: bool,
    changed_lines: dict,
) -> None:
    """Raise FixTooLongError when the fix exceeds line-count limits.

    Two checks:
      1. Absolute limit  — fix_code must not exceed MAX_FIX_LINES(_COMPLEX).
      2. Over-rewrite    — surgical fixes that silently rewrote >15 % of the
         file are rejected; they should have used changed_lines instead.
    """
    total_lines = fix_code.count("\n")
    max_lines = MAX_FIX_LINES_COMPLEX if complex_mode else MAX_FIX_LINES
    if total_lines > max_lines:
        raise FixTooLongError(f"Fix has {total_lines} lines — exceeds {max_lines}")

    if not complex_mode and code_context and code_context.count("\n") > 10 and not changed_lines:
        original_lines = code_context.count("\n")
        max_allowed_change = max(5, int(original_lines * 0.15))
        if abs(total_lines - original_lines) > max_allowed_change:
            raise FixTooLongError(
                f"Fix changed too much: {total_lines} vs {original_lines} original. "
                "Use 'changed_lines' for surgical fixes."
            )


def resolve_bugs_found(
    parsed: dict,
    fix_code: str,
    changed_lines: dict,
    code_context: str,
) -> list[str]:
    """Build the final bugs_found list using a three-tier hierarchy.

    Tier 0 — AUTO-HEAL comments in fix_code (full-rewrite mode).
        Parses # AUTO-HEAL annotations, filters hallucinated/unchanged-line
        comments, and deduplicates by proximity and description key.

    Tier 1 — changed_lines annotations (surgical mode).
        Synthesises descriptions from the AUTO-HEAL comments in each changed
        line dict entry.

    Tier 3 — explicit bug_count from JSON (last resort).
        Generates generic placeholder entries so the PR never shows 0 bugs
        when the LLM did state how many it fixed.
    """
    bugs_found = parsed.get("bugs_found", [])

    # Tier 0: full-rewrite path — parse AUTO-HEAL comments from fix_code.
    # AUTO-HEAL annotations are always more accurate than the LLM's bugs_found
    # list because they are derived directly from the changed lines in the fix.
    # We cap the result at the LLM's declared bug_count (only downward) to
    # prevent retry inflation: on retries the LLM sometimes adds AUTO-HEAL to
    # every touched line, inflating the count well above the real bug count.
    if fix_code and not changed_lines:
        autoheal_bugs, autoheal_lines = collect_autoheal_bugs(fix_code, code_context)
        if autoheal_bugs:
            changed_lines.update(autoheal_lines)
            llm_bug_count = parsed.get("bug_count")
            if isinstance(llm_bug_count, int) and 1 <= llm_bug_count < len(autoheal_bugs):
                bugs_found = autoheal_bugs[:llm_bug_count]
            else:
                bugs_found = autoheal_bugs

    # Tier 1: surgical path — synthesise from changed_lines.
    if not bugs_found and changed_lines:
        bugs_found = collect_changed_line_bugs(changed_lines, fix_code, code_context)

    # Tier 3: fallback — use LLM's explicit bug_count to generate placeholders.
    if not bugs_found:
        llm_bug_count = parsed.get("bug_count")
        if isinstance(llm_bug_count, int) and 1 <= llm_bug_count <= 50:
            bugs_found = [
                f"Bug {i}: identified in full rewrite — see explanation"
                for i in range(1, llm_bug_count + 1)
            ]

    return bugs_found
