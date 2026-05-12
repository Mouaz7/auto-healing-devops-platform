"""AUTO-HEAL comment parser — extracts bug descriptions from LLM-generated fixes.

The LLM is instructed to annotate every changed line with:
    # AUTO-HEAL: was '<old code>' (<bug type>) -> <what was fixed>

This module parses those annotations to build:
  - A deduplicated list of logical bugs (bugs_found)
  - A mapping of changed line numbers (changed_lines)

Two entry points:
  - collect_autoheal_bugs()  — Tier 0: full-rewrite mode (fix_code provided)
  - collect_changed_line_bugs() — Tier 1: surgical mode (changed_lines from LLM JSON)
"""
from __future__ import annotations

import ast
import re

_AUTOHEAL_PATTERN = re.compile(r"#\s*AUTO-HEAL:\s*(.+)")
_AUTOHEAL_PROXIMITY = 4   # max lines between two fixes of the same logical bug

_RE_WAS_SNIPPET  = re.compile(r"was\s+'([^']+)'")
_RE_WAS_CATEGORY = re.compile(r"was\s+[^(]*\(([^)]+)\)")
_RE_HAS_WAS      = re.compile(r"\bwas\b", re.IGNORECASE)

_STYLE_PREFIXES = ("introduced", "renamed", "added for", "replaced for", "refactored")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _autoheal_key(desc: str) -> str:
    """Deduplication key for an AUTO-HEAL description.

    Priority: was-expression → was-category → colon-phrase → first two words.
    """
    m = _RE_WAS_SNIPPET.search(desc)
    if m:
        return m.group(1).strip().lower()
    m = _RE_WAS_CATEGORY.search(desc)
    if m:
        return m.group(1).lower().strip()
    if ":" in desc:
        return desc.split(":")[0].lower().strip()
    words = desc.lower().split()
    return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else desc)


def _is_style_change(desc: str) -> bool:
    """True when an AUTO-HEAL comment describes a rename/style change, not a bug."""
    return desc.lower().startswith(_STYLE_PREFIXES)


def _build_fn_scopes(source: str) -> dict[int, str]:
    """Map every line number in *source* to its enclosing function name.

    Returns an empty dict on SyntaxError so callers fall back to module-level
    (no-scope) deduplication.
    """
    scopes: dict[int, str] = {}
    try:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno)
                scope = f"{node.name}:{node.lineno}"
                for ln in range(node.lineno, end + 1):
                    scopes[ln] = scope
    except SyntaxError:
        pass
    return scopes


def _orig_line_set(code_context: str) -> set[str]:
    """Return stripped non-empty lines from the original code as a set.

    AUTO-HEAL comments are stripped before adding so that previously-fixed
    lines (which already carry '# AUTO-HEAL: …' suffixes) still match the
    bare code_part produced from a new fix attempt.
    """
    result: set[str] = set()
    for ln in code_context.splitlines():
        stripped = ln.strip()
        if not stripped:
            continue
        if "# AUTO-HEAL:" in stripped:
            stripped = stripped.split("# AUTO-HEAL:", 1)[0].rstrip()
        if stripped:
            result.add(stripped)
    return result


def _is_unchanged(code_part: str, orig_lines: set[str]) -> bool:
    """True when the code part of an AUTO-HEAL line exists unchanged in the original."""
    return code_part.strip() in orig_lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_bugs_meaningful(bugs: list) -> bool:
    """True when the LLM returned a real, non-degenerate bugs_found list.

    Falls through to AUTO-HEAL heuristics when the list is empty, all-identical
    (LLM echoed the same error N times), or a single entry too short to be useful.
    """
    if not bugs:
        return False
    entries = {str(x).strip() for x in bugs}
    if len(entries) == 1 and (len(bugs) > 1 or len(next(iter(entries))) < 15):
        return False
    return True


def collect_autoheal_bugs(
    fix_code: str,
    code_context: str,
) -> tuple[list[str], dict[str, str]]:
    """Tier 0 — parse AUTO-HEAL annotations from a full-rewrite fix_code.

    Returns:
        (bugs, changed_lines) where bugs is a deduplicated list of bug
        descriptions and changed_lines maps line numbers to fixed code.

    Filters applied per line:
      1. Unchanged-line guard  — code part identical to original → skip
      2. Format guard          — no 'was X' in description → helper line, skip
      3. Proximity dedup       — same key within _AUTOHEAL_PROXIMITY lines → skip
      4. Style-change filter   — rename/refactor prefix → skip
    """
    bugs: list[str] = []
    lines_map: dict[str, str] = {}
    fn_scopes = _build_fn_scopes(fix_code)
    orig_lines = _orig_line_set(code_context)
    last_seen: dict[tuple, int] = {}

    for lineno, line in enumerate(fix_code.splitlines(), 1):
        m = _AUTOHEAL_PATTERN.search(line)
        if not m:
            continue
        desc = m.group(1).strip()
        code_part = line.split("# AUTO-HEAL:", 1)[0].rstrip()

        if _is_unchanged(code_part, orig_lines):
            continue
        if not _RE_HAS_WAS.search(desc):
            continue

        lines_map[str(lineno)] = line.rstrip()
        key = (fn_scopes.get(lineno, "module"), _autoheal_key(desc))
        last_ln = last_seen.get(key, -999)
        last_seen[key] = lineno
        if lineno - last_ln <= _AUTOHEAL_PROXIMITY:
            continue
        if _is_style_change(desc):
            continue

        bugs.append(f"Line {lineno}: {desc[:160]}")

    return bugs, lines_map


def collect_changed_line_bugs(
    changed_lines: dict[str, str],
    fix_code: str,
    code_context: str,
) -> list[str]:
    """Tier 1 — synthesise bug descriptions from a surgical changed_lines dict.

    Used when the LLM returned changed_lines directly (surgical mode) and
    bugs_found is still empty after Tier 0.

    Applies the same unchanged-line and format guards as Tier 0.
    """
    bugs: list[str] = []
    fn_scopes = _build_fn_scopes(fix_code) if fix_code else {}
    orig_lines = _orig_line_set(code_context)
    last_seen: dict[tuple, int] = {}

    for lineno_str, new_code in sorted(
        changed_lines.items(),
        key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
    ):
        ln_int = int(lineno_str) if str(lineno_str).isdigit() else 0
        comment = (
            new_code.split("# AUTO-HEAL:", 1)[1].strip()
            if "# AUTO-HEAL:" in new_code
            else ""
        )
        code_part = new_code.split("# AUTO-HEAL:", 1)[0].rstrip()

        if _is_unchanged(code_part, orig_lines):
            continue
        if comment and not _RE_HAS_WAS.search(comment):
            continue

        key = (
            fn_scopes.get(ln_int, "module"),
            _autoheal_key(comment) if comment else f"line:{lineno_str}",
        )
        last_ln = last_seen.get(key, -999)
        last_seen[key] = ln_int
        if ln_int - last_ln <= _AUTOHEAL_PROXIMITY:
            continue
        if comment and _is_style_change(comment):
            continue

        if comment:
            bugs.append(f"Line {lineno_str}: {comment[:120]}")
        else:
            bugs.append(f"Line {lineno_str}: fixed → `{new_code.strip()[:80]}`")

    return bugs
