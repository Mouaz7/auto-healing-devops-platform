"""PR bug-table builders — construct the Bug → Fix markdown table and detail blocks."""
from __future__ import annotations

import re as _re

_AUTOHEAL_COMMENT_RE = _re.compile(r"\s*#\s*AUTO-HEAL:.*$")
_AUTOHEAL_WAS_RE     = _re.compile(r"#\s*AUTO-HEAL:\s*was '(.+?)'\s*(.+?)-> (.+)")
_LINE_PREFIX_RE      = _re.compile(r"^Line \d+(?:\s*\(\d+ changes?\))?:\s*")


def build_bug_table(
    changed_lines: dict,
    scan_findings: list,
    bugs_found: list,
    orig_lines_list: list[str],
    parse_error: str,
    root_c: str,
) -> tuple[str, str]:
    """Return ``(bug_table_str, bug_details_str)`` for inclusion in the PR body.

    Priority: changed_lines (diff-based, exact) > scan_findings (AST scanner)
    > bugs_found (LLM text only).
    """
    _syntax_lineno = 0
    m = _re.search(r"line[:\s]+(\d+)", parse_error + " " + root_c, _re.IGNORECASE)
    if m:
        _syntax_lineno = int(m.group(1))

    if changed_lines:
        return _table_from_changed_lines(changed_lines, bugs_found, orig_lines_list)
    if scan_findings:
        return _table_from_scan_findings(scan_findings, changed_lines, orig_lines_list)
    if bugs_found:
        return _table_from_bugs_found(bugs_found, orig_lines_list, _syntax_lineno)
    return "_No bugs identified — see fix explanation below._", ""


def annotate_original(orig_lines_list: list[str], patch: str) -> str:
    """Return the original file with ``# ← BUG:`` markers on changed lines."""
    bug_map: dict[int, str] = {}
    for fixed_line in (patch or "").splitlines():
        m = _AUTOHEAL_WAS_RE.search(fixed_line)
        if not m:
            continue
        old_snippet = m.group(1).strip()
        fix_desc    = m.group(3).strip()[:60]
        for i, orig_line in enumerate(orig_lines_list):
            if old_snippet and old_snippet in orig_line:
                bug_map[i] = fix_desc
                break

    annotated = []
    for i, line in enumerate(orig_lines_list[:80]):
        annotated.append(f"{line}  # ← BUG: {bug_map[i]}" if i in bug_map else line)
    if len(orig_lines_list) > 80:
        annotated.append(f"# ... ({len(orig_lines_list) - 80} more lines)")
    return "\n".join(annotated)


# ------------------------------------------------------------------
# Internal builders
# ------------------------------------------------------------------

def _table_from_changed_lines(
    changed_lines: dict,
    bugs_found: list[str],
    orig_lines_list: list[str],
) -> tuple[str, str]:
    line_bug_index: dict[int, str] = {}
    for bd in bugs_found:
        m = _re.match(r"Line (\d+)", bd)
        if m:
            k = int(m.group(1))
            if k not in line_bug_index:
                line_bug_index[k] = bd

    rows = [
        "| # | Line | Buggy Code (original) | Fixed Code | Bug Description |",
        "|---|------|----------------------|------------|-----------------|",
    ]
    details = []
    sorted_lines = sorted(
        changed_lines.items(),
        key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
    )
    for i, (lineno_str, new_code) in enumerate(sorted_lines, 1):
        lineno   = int(lineno_str) if str(lineno_str).isdigit() else 0
        old_code = _orig_line(orig_lines_list, lineno)
        fixed    = _AUTOHEAL_COMMENT_RE.sub("", new_code).strip()
        raw_desc = line_bug_index.get(lineno) or (
            bugs_found[i - 1] if i - 1 < len(bugs_found) else "—"
        )
        desc = _LINE_PREFIX_RE.sub("", raw_desc)
        rows.append(
            f"| {i} | `{lineno}` | `{old_code or '—'}` | `{fixed or '—'}` | {desc[:80]} |"
        )
        details.append(
            f"### {i}. 🔴 Line `{lineno}`\n\n"
            f"> **Bug:** {desc}\n\n"
            f"| | Code |\n|---|------|\n"
            f"| 🔴 **Original (line {lineno})** | `{old_code or '—'}` |\n"
            f"| ✅ **Fixed** | `{fixed or '_(see fixed file)_'}` |\n"
        )
    return "\n".join(rows), "\n\n".join(details)


def _table_from_scan_findings(
    scan_findings: list,
    changed_lines: dict,
    orig_lines_list: list[str],
) -> tuple[str, str]:
    sev_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "INFO": "🔵"}
    rows = [
        "| # | Severity | Line | Buggy Code (original) | Pattern | Fix |",
        "|---|----------|------|-----------------------|---------|-----|",
    ]
    details = []
    for i, f in enumerate(scan_findings, 1):
        icon     = sev_icon.get(f.get("severity", "HIGH"), "🔴")
        lineno   = f.get("line", 0)
        old_code = _orig_line(orig_lines_list, lineno)
        fixed_c  = changed_lines.get(str(lineno), f.get("suggestion", "—"))
        if hasattr(fixed_c, "strip"):
            fixed_c = fixed_c.strip()
        rows.append(
            f"| {i} | {icon} {f.get('severity','HIGH')} | `{lineno or '—'}` "
            f"| `{old_code or '—'}` | `{f['pattern']}` | {f.get('suggestion','—')[:60]} |"
        )
        details.append(
            f"### {i}. {icon} Line `{lineno or '?'}` — `{f['pattern']}` ({f.get('severity','HIGH')})\n\n"
            f"> {f['message']}\n\n"
            f"| | Code |\n|---|------|\n"
            f"| 🔴 **Original (line {lineno or '?'})** | `{old_code or '—'}` |\n"
            f"| ✅ **Fixed** | `{str(fixed_c) or f.get('suggestion','—')}` |\n"
        )
    return "\n".join(rows), "\n\n".join(details)


def _table_from_bugs_found(
    bugs_found: list[str],
    orig_lines_list: list[str],
    syntax_lineno: int,
) -> tuple[str, str]:
    rows    = ["| # | Line | Bug Description |", "|---|------|-----------------|"]
    details = []
    for i, bug_desc in enumerate(bugs_found, 1):
        lineno   = syntax_lineno if i == 1 and syntax_lineno else 0
        old_code = _orig_line(orig_lines_list, lineno)
        line_str = f"`{lineno}`" if lineno else "—"
        rows.append(f"| {i} | {line_str} | {bug_desc[:100]} |")
        details.append(
            f"### {i}. 🔴 {'Line `' + str(lineno) + '`' if lineno else 'Bug'}\n\n"
            f"> {bug_desc}\n\n"
            f"| | Code |\n|---|------|\n"
            f"| 🔴 **Original{' (line ' + str(lineno) + ')' if lineno else ''}** | `{old_code or '—'}` |\n"
            f"| ✅ **Fixed** | _(see fixed file below)_ |\n"
        )
    return "\n".join(rows), "\n\n".join(details)


def _orig_line(orig_lines_list: list[str], lineno: int) -> str:
    if orig_lines_list and lineno and 0 <= lineno - 1 < len(orig_lines_list):
        return orig_lines_list[lineno - 1].strip()
    return ""
