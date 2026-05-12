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
    it into the prompt so the LLM has static-analysis hints alongside the code.
    Chooses between the surgical (SCENARIO_A) and full-rewrite (COMPLEX_REPAIR)
    templates based on *complex_mode*.
    """
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
