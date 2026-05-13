"""Prompt construction and retry-budget calculation for the fix generator.

Answers the question: "What do I send to the LLM?"

Public API:
  - build_fix_prompt()        — pick template + system message for this run
  - compute_attempt_budget()  — scale retry count with bug density
"""
from __future__ import annotations

from src.llm_mcp.bug_scanner import BugPatternScanner
from src.llm_mcp.fix_prompts import extract_bug_list
from src.llm_mcp.prompt_templates import (
    COMPLEX_REPAIR_TEMPLATE,
    COMPLEX_SYSTEM_PROMPT,
    MAX_RETRIES,
    SCENARIO_A_TEMPLATE,
    SYSTEM_PROMPT,
)
from src.shared.models import FailureAnalysis


def build_fix_prompt(
    complex_mode: bool,
    analysis: FailureAnalysis,
    compressed_logs: str,
    code_context: str,
    memory_ctx: str,
    bug_count: int,
) -> tuple[str, str]:
    """Return (user_prompt, system_prompt) for this fix attempt.

    Annotates code_context with BugPatternScanner findings before inserting
    it into the prompt. Scanner findings also force complex_mode when 2+
    patterns are detected — ensuring the LLM does a full file repair even
    when the build log only contains one error (e.g. a SyntaxError that hid
    all the underlying logic bugs).
    """
    memory_block = f"\n{memory_ctx}\n" if memory_ctx else ""
    scan_result = BugPatternScanner.scan(code_context)
    scan_block = scan_result.to_prompt_block()
    annotated_context = scan_block + code_context if scan_block else code_context

    # Elevate to complex mode when scanner finds 2+ patterns so the LLM is
    # asked for a full file repair rather than a minimal single-error fix.
    scanner_bug_count = len(scan_result.findings)
    if scanner_bug_count >= 2:
        complex_mode = True

    # Effective bug count is max of log-derived count and scanner count so the
    # retry budget scales correctly even when logs only show one error type.
    effective_bug_count = max(bug_count, scanner_bug_count)

    if complex_mode:
        log_bugs = extract_bug_list(compressed_logs)
        scanner_bugs = [
            f"Line {f.line}: {f.pattern} — {f.message}"
            + (f" Fix: {f.suggestion}" if f.suggestion else "")
            for f in scan_result.findings
        ]
        # Merge log bugs + scanner bugs, deduplicate by content
        seen: set[str] = set()
        merged_bugs: list[str] = []
        for b in log_bugs + scanner_bugs:
            key = b[:60]
            if key not in seen:
                seen.add(key)
                merged_bugs.append(b)
        bug_list_str = (
            "\n".join(f"  - {b}" for b in merged_bugs)
            or "  - Multiple errors detected — perform full file review"
        )
        prompt = COMPLEX_REPAIR_TEMPLATE.format(
            error_type=analysis.error_type.value,
            root_cause=analysis.root_cause,
            affected_files=", ".join(analysis.affected_files),
            cleaned_logs=compressed_logs,
            code_context=annotated_context,
            memory_context=memory_block,
            bug_count=effective_bug_count,
            bug_list=bug_list_str,
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


def compute_attempt_budget(bug_count: int) -> int:
    """Scale the retry count with bug density.

    ≤2 bugs → 6 attempts  (simple fixes converge quickly)
    3–9     → MAX_RETRIES + 2
    10–40   → MAX_RETRIES + 6  (high-density files need more room)
    """
    if bug_count >= 10:
        return MAX_RETRIES + 6
    if bug_count >= 3:
        return MAX_RETRIES + 2
    return 6
