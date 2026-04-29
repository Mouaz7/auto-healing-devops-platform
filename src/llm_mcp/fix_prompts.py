"""Prompt-building helpers for the fix generator's retry loop."""
from __future__ import annotations

import re


def build_retry_prompt(original_prompt: str, failed_attempts: list[dict]) -> str:
    """Construct a retry prompt that shows ALL prior failures.

    Replaces the user message rather than appending — appending caused the
    message to grow unbounded across retries and let the LLM lose track of
    the original task.

    If the last 2 attempts produced the SAME error message, the LLM is stuck
    in a loop. We then prepend a STRATEGY PIVOT directive forcing it to throw
    away its previous approach.
    """
    stuck = False
    if len(failed_attempts) >= 2:
        last = failed_attempts[-1]["err"][:120]
        prev = failed_attempts[-2]["err"][:120]
        stuck = last == prev

    parts = [original_prompt, "", "=" * 60, "PRIOR FAILED ATTEMPTS", "=" * 60]
    if stuck:
        parts.extend([
            "",
            "*** STRATEGY PIVOT REQUIRED ***",
            "Your last two attempts produced the SAME error. You are in a loop.",
            "Throw away your previous approach completely. Re-read the original",
            "code from scratch. Identify ALL bugs first (full Scan Phase). Write",
            "the entire file from a blank slate — do not edit your previous fix.",
            "",
        ])
    for fa in failed_attempts:
        parts.append("")
        parts.append(f"--- Attempt {fa['attempt']} ({fa['kind']}) FAILED ---")
        parts.append(f"Error: {fa['err']}")
        parts.append(f"Your previous fix_code began with:\n{fa['fix_preview']}")
    parts.extend([
        "",
        "=" * 60,
        "INSTRUCTIONS FOR THIS ATTEMPT",
        "=" * 60,
        "1. Read EVERY prior error above. Do NOT submit a fix that produces",
        "   any of the same errors.",
        "2. The original code may contain MULTIPLE INTERACTING BUGS. Look at",
        "   every line — typos in subscripts (a[a]), wrong variable names",
        "   (low instead of array), forgotten function calls (bare tuples),",
        "   undefined variables in scope, off-by-one. Fix ALL of them in one",
        "   pass — surgical patches will not converge for multi-bug files.",
        "3. Before returning fix_code, mentally run the program with the",
        "   default arguments and verify no NameError, TypeError, or",
        "   IndexError can occur.",
        "4. Preserve initialisation guards (e.g. `if x is None: x = ...`).",
    ])
    return "\n".join(parts)


def extract_bug_list(logs: str) -> list[str]:
    """Pull distinct error messages from logs for the complex-mode prompt."""
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
    bugs: list[str] = []
    seen: set[str] = set()
    for p in patterns:
        for m in re.finditer(p, logs, re.IGNORECASE):
            msg = m.group(1).strip()[:120]
            if msg not in seen:
                bugs.append(msg)
                seen.add(msg)
    return bugs[:10]
