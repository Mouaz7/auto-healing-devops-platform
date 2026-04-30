"""Prompt-building helpers for the fix generator's retry loop."""
from __future__ import annotations

import re

_ERROR_FP_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:Error|Exception))\b[:.\s]*([^\n]{0,80})"
)
_TMP_PATH_RE = re.compile(r"/tmp/\S+\.py|line \d+")


def _error_fingerprint(err: str) -> str:
    """Return a normalised fingerprint for an error string.

    Strips tmp paths and line numbers so that two TypeErrors with the same
    root cause but different temp filenames compare as equal — the previous
    raw-string comparison missed this and the STRATEGY PIVOT never fired.
    """
    m = _ERROR_FP_RE.search(err)
    if m:
        suffix = _TMP_PATH_RE.sub("", m.group(2)).strip()
        return f"{m.group(1)}::{suffix[:60]}"
    return err[:80]


def build_retry_prompt(original_prompt: str, failed_attempts: list[dict]) -> str:
    """Construct a retry prompt that shows ALL prior failures.

    Replaces the user message rather than appending — appending caused the
    message to grow unbounded across retries and let the LLM lose track of
    the original task.

    If the last 2 attempts hit the same error TYPE (after normalising tmp
    paths and line numbers), the LLM is stuck. We then prepend a STRATEGY
    PIVOT directive forcing it to look at call sites instead of the failing
    line.
    """
    stuck = False
    if len(failed_attempts) >= 2:
        last_fp = _error_fingerprint(failed_attempts[-1]["err"])
        prev_fp = _error_fingerprint(failed_attempts[-2]["err"])
        stuck = last_fp == prev_fp

    parts = [original_prompt, "", "=" * 60, "PRIOR FAILED ATTEMPTS", "=" * 60]
    if stuck:
        last_err  = failed_attempts[-1]["err"]
        last_kind = failed_attempts[-1].get("kind", "")
        if "SyntaxError" in last_err or last_kind == "syntax":
            # Surgical changed_lines patches keep producing broken indentation —
            # force the LLM to abandon the line-by-line approach.
            parts.extend([
                "",
                "*** STRATEGY PIVOT — STRUCTURE BROKEN ***",
                "Your surgical patches keep producing SyntaxErrors. Editing",
                "individual lines is mangling indentation context.",
                "",
                "STOP using `changed_lines`. Return the ENTIRE corrected file",
                "in `fix_code` — every line, top to bottom, with consistent",
                "4-space indentation. Re-read the original code from line 1,",
                "write it out from scratch with all bugs fixed in one pass.",
                "",
            ])
        else:
            # Runtime errors that repeat are usually call-site bugs the LLM
            # missed because the traceback points at the symptom, not the cause.
            parts.extend([
                "",
                "*** STRATEGY PIVOT REQUIRED ***",
                "Your last two attempts hit the SAME error type. You are in a loop.",
                "",
                "STOP editing the failing line. The bug is somewhere ELSE — most",
                "commonly at a CALL SITE that passes wrong arguments, or a missing",
                "return statement that makes a downstream value None.",
                "",
                "Step 1: list every call site of the failing function in the file.",
                "Step 2: list every function whose return value flows into the",
                "        failing operand.",
                "Step 3: write the fix. It will almost certainly be on a different",
                "        line than where the traceback points.",
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
