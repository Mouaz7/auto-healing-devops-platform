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
            if "IndexError" in err and "list index out of range" in err:
                err += (
                    "\n\n*** OFF-BY-ONE HINT ***\n"
                    "IndexError 'list index out of range' almost always means a loop "
                    "bound is one too large. Common patterns:\n"
                    "  1. range(len(x) + 1) should be range(len(x))\n"
                    "  2. range(len(x)) with x[i+1] inside — stop at len(x)-1\n"
                    "  3. range(1, len(x)+1) off by one at the end\n"
                    "Check EVERY loop bound and EVERY index expression in the function."
                )
            if "AssertionError" in err:
                assert_line = ""
                m = re.search(r"AssertionError[^\n]*\n?([^\n]{0,120})", err)
                if m:
                    assert_line = m.group(1).strip()
                err += (
                    "\n\n*** SILENT BUG HINT ***\n"
                    "An AssertionError means the code runs without crashing but "
                    "produces WRONG OUTPUT. Do NOT look for crashes — look for:\n"
                    "  1. Wrong operator: `==` used instead of `+=` or `-=`\n"
                    "     (comparison `total == num` is a no-op, not accumulation)\n"
                    "  2. Wrong return value on edge case: `return 1` or `return None`\n"
                    "     instead of a computed result (e.g. `return 0` for empty list)\n"
                    "  3. Mutable default argument: `def f(x, lst=[])` shares the same\n"
                    "     list object across ALL calls — use `lst=None` then `lst = lst or []`\n"
                    "  4. Missing accumulation: loop body does not update any variable\n"
                    + (f"  Assert context: {assert_line}\n" if assert_line else "")
                    + "Trace the data flow step by step from input to output."
                )
            if "RecursionError" in err or "maximum recursion depth" in err:
                err += (
                    "\n\n*** RECURSION HINT ***\n"
                    "RecursionError means the function calls itself forever — the base "
                    "case is missing or unreachable.\n"
                    "  1. Does the base case exist? (e.g. `if n <= 1: return n`)\n"
                    "  2. Is the condition too strict? `n == 0` misses negative or n=1 —\n"
                    "     use `n <= 1` for Fibonacci/factorial.\n"
                    "  3. Does each recursive call move TOWARD the base case?\n"
                    "     `fib(n-1)` converges; `fib(n)` or `fib(n+1)` loops forever.\n"
                    "Find the recursive function and verify every code path reaches "
                    "a `return` that does NOT recurse."
                )
            if "AttributeError" in err and "NoneType" in err and "has no attribute" in err:
                attr_match = re.search(r"has no attribute '([^']+)'", err)
                attr_name = attr_match.group(1) if attr_match else ""
                err += (
                    "\n\n*** MISSING RETURN HINT ***\n"
                    f"AttributeError: NoneType has no attribute "
                    f"'{attr_name}' means a function returned None when it should "
                    "have returned an object.\n"
                    "  1. In recursive traversal: does the recursive call get RETURNED?\n"
                    "     `return self.next.find(x)` — not just `self.next.find(x)`\n"
                    "  2. Does every branch of the function end with `return <value>`?\n"
                    "  3. In search functions: is there a `return node` (not just `return`)\n"
                    "     when the target is found?\n"
                    "Find every function in the traceback chain and check ALL return paths."
                )
            if "KeyError" in err:
                key_match = re.search(r"KeyError: ([^\n]+)", err)
                key_info = key_match.group(1).strip() if key_match else ""
                err += (
                    "\n\n*** MISSING KEY GUARD HINT ***\n"
                    + (f"KeyError: {key_info} — " if key_info else "KeyError — ")
                    + "you accessed a dict key that does not exist yet.\n"
                    "  1. For memo/cache: check `if n not in memo:` before `memo[n]`\n"
                    "  2. Use safe access: `memo.get(n)` returns None instead of crashing\n"
                    "  3. For counters: `counts[k] = counts.get(k, 0) + 1`\n"
                    "  4. Build the entry BEFORE reading it: compute, then store, then return\n"
                    "Find every `dict[variable]` and replace with a guarded pattern."
                )
            if "ZeroDivisionError" in err:
                err += (
                    "\n\n*** ZERO DIVISION HINT ***\n"
                    "ZeroDivisionError means the denominator is zero. Add a guard:\n"
                    "  1. For averages: `if not numbers: return 0.0` before dividing\n"
                    "  2. Inline guard: `return (total / n) if n else 0.0`\n"
                    "  3. For percentages: `return (a / b * 100) if b else 0`\n"
                    "Find every `/` and `//` operator and check if the denominator "
                    "can be zero when the input is empty or all-zero."
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
            f"INFINITE LOOP: code did not finish within {timeout_s}s — "
            "your fix still has a bug.\n\n"
            "*** INFINITE LOOP HINT ***\n"
            "Common causes:\n"
            "  1. Binary search: `low = mid` / `high = mid` instead of\n"
            "     `low = mid + 1` / `high = mid - 1` — mid never moves past\n"
            "  2. While-loop condition never becomes False: check that the\n"
            "     loop variable is updated INSIDE the loop body\n"
            "  3. Recursive call with the same arguments: `f(n)` calls `f(n)`\n"
            "     — ensure the argument shrinks toward the base case\n"
            "  4. Missing `break` or `return` inside a `while True:` loop\n"
            "Mentally run one iteration: does the state change toward termination?"
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
