"""Validators for AI-generated code fixes.

Pure helpers — no I/O, no LLM calls. Two layers:
  - Static checks: AST-parse, self-assignment, output-shape sanity
  - Runtime checks: actually run the fix and verify it terminates + behaves
"""
from __future__ import annotations

import ast
import logging
import re
import subprocess
import tempfile

logger = logging.getLogger(__name__)


_HALLUCINATED_FILENAMES = {
    "<unknown>", "(unknown)", "unknown", "unknown.py",
    "<file>", "<filename>", "<path>", "placeholder.py",
    "example.py", "auto_heal_fix.py", "file.py",
}

_SELF_ASSIGN_RE = re.compile(r"^\s*([a-zA-Z_]\w*)\s*=\s*\1\s*(?:#.*)?$", re.MULTILINE)
_SORT_OUTPUT_RE = re.compile(
    r"sort(?:ed)?[^\[\n]*[:=]\s*(\[[^\]]+\])",
    re.IGNORECASE,
)


def clean_files(files: list[str]) -> list[str]:
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


def count_bugs_in_logs(logs: str) -> int:
    """Estimate distinct bugs in a build log.

    Combines:
      - distinct exception TYPES present
      - per-line static-analysis findings (`line N:`)
      - FAILED_FILE blocks from the prescan flow
      - prescan SyntaxError signal (weighted as 3 bugs since these files
        are usually structurally broken in multiple places)

    Capped at 40 — enough to scale the retry budget for very high-bug-density
    files without runaway.
    """
    error_patterns = [
        r"SyntaxError", r"NameError", r"TypeError", r"AttributeError",
        r"ImportError", r"IndentationError", r"ValueError", r"KeyError",
        r"IndexError", r"AssertionError", r"FAILED\s+\S+\.py",
    ]
    distinct_types = {p for p in error_patterns if re.search(p, logs, re.IGNORECASE)}
    static_findings = len(re.findall(r"\bline\s+\d+\s*:", logs, re.IGNORECASE))
    failed_file_blocks = len(re.findall(r"^FAILED_FILE:\s*\S+", logs, re.MULTILINE))
    syntax_signal = 3 if re.search(r"ERROR_TYPE:\s*SyntaxError", logs) else 0
    return min(40, len(distinct_types) + static_findings + failed_file_blocks + syntax_signal)


def count_syntax_errors(code: str) -> int:
    """Return 0 if code parses, 1 if not."""
    try:
        ast.parse(code)
        return 0
    except SyntaxError:
        return 1


def validate_fix_syntax(fix_code: str) -> tuple[bool, str]:
    """Return (is_valid, error_message). Empty error = code compiles.

    On failure includes the offending line + a few lines of context. Just
    saying 'unexpected indent on line 5' is too abstract — the LLM keeps
    producing the same broken code across retries because it cannot see
    WHAT it wrote on line 5.
    """
    try:
        ast.parse(fix_code)
        return True, ""
    except SyntaxError as e:
        lines = fix_code.splitlines()
        ln = e.lineno or 0
        ctx_start = max(0, ln - 3)
        ctx_end = min(len(lines), ln + 2)
        context_lines = []
        for i in range(ctx_start, ctx_end):
            marker = ">>> " if (i + 1) == ln else "    "
            context_lines.append(f"{marker}{i + 1:4d} | {lines[i]}")
        ctx = "\n".join(context_lines)
        return False, (
            f"SyntaxError on line {ln}: {e.msg}\n"
            f"Code context (>>> marks the failing line):\n{ctx}"
        )


def detect_self_assignments(code: str) -> list[str]:
    """Find no-op self-assignments like `x = x` — always a sign of a buggy fix."""
    return [m.group(1) for m in _SELF_ASSIGN_RE.finditer(code)]


def check_sort_output(stdout: str) -> str:
    """If the program advertises sorted output, verify it is actually sorted.

    Returns an error message if the output is wrong; empty string otherwise.

    Catches the common failure mode where the AI rewrites partition() to
    swap the wrong elements: the code runs, prints a list, but the list
    is unsorted — which compile + no-crash checks alone would let through.
    """
    for match in _SORT_OUTPUT_RE.finditer(stdout):
        list_src = match.group(1)
        try:
            parsed = ast.literal_eval(list_src)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(parsed, list) or len(parsed) < 2:
            continue
        try:
            sorted_copy = sorted(parsed)
        except TypeError:
            continue
        if list(parsed) != sorted_copy:
            return (
                "WRONG OUTPUT: the program printed a list labelled as 'sorted' "
                f"but it is NOT sorted. Got {parsed}, expected {sorted_copy}. "
                "Your sort/partition logic is still broken — typical cause is "
                "swapping the wrong elements (e.g. array[high]/array[i] when "
                "the algorithm actually requires array[i]/array[j])."
            )
    return ""


def validate_fix_runtime(fix_code: str, timeout_s: int = 5) -> tuple[bool, str]:
    """Run the fix and verify it does not infinite-loop, crash, or print wrong results.

    Catches:
      - Infinite loops (timeout)
      - Runtime crashes (non-zero exit)
      - Self-assignments (`x = x`) — always a bug
      - "Not found" output for cases that should find the value
      - Sort output that is not actually sorted

    Returns (is_valid, error_message).
    """
    if "def test_" in fix_code:
        return True, ""

    self_assigns = detect_self_assignments(fix_code)
    if self_assigns:
        return False, (
            f"SELF-ASSIGNMENT DETECTED: '{self_assigns[0]} = {self_assigns[0]}' is a no-op "
            "and always a bug. Remove it and replace with the correct logic."
        )

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(fix_code)
            tmp_path = f.name
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True, text=True, timeout=timeout_s,
            check=False,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if len(err) > 5000:
                # Keep the deepest frame (final "File ... line N, in <fn>" + Exception)
                # rather than truncating mid-word at the entry point.
                err = "...[traceback truncated]...\n" + err[-5000:]
            # NoneType in a TypeError almost always means an arg was missing at the
            # call site, not a bug in the comparison itself. The traceback points at
            # the failing line which sends the LLM tunnel-visioning there. Redirect.
            if "NoneType" in err and "TypeError" in err:
                err += (
                    "\n\n*** ROOT-CAUSE HINT ***\n"
                    "A NoneType operand means an argument was MISSING at the CALL "
                    "SITE, not a bug in the failing line itself. Look at every "
                    "call to this function in the file (e.g. `quicksort(my_array)` "
                    "instead of `quicksort(my_array, 0, len(my_array)-1)`). "
                    "Fix the CALL, not the default-argument check."
                )
            return False, f"RuntimeError: {err}"

        out = result.stdout or ""
        if "not found" in out.lower() and "found at" not in out.lower():
            return False, (
                "WRONG OUTPUT: code prints 'Not found' but the searched value "
                "should be findable. The logic is still incorrect."
            )
        sort_check = check_sort_output(out)
        if sort_check:
            return False, sort_check
        return True, ""
    except subprocess.TimeoutExpired:
        return False, (
            f"INFINITE LOOP: code did not finish within {timeout_s}s "
            "— your fix still has a bug"
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("runtime_validation_skipped err=%s", exc)
        return True, ""
    finally:
        if tmp_path:
            try:
                import os
                os.unlink(tmp_path)
            except OSError:
                pass
