"""Pure helpers used by the pipeline mixin — no I/O, no state.

Kept module-level (not methods) so they can be unit-tested without a server.
"""
from __future__ import annotations

import re

# Maps free-form raw ERROR_TYPE strings (e.g. 'STATIC_ANALYSIS_LOGIC_BUG',
# 'WRONG_SORT_OUTPUT') to the ErrorType enum values that LLM-mcp accepts.
# Anything we cannot map cleanly falls back to VALUE_ERROR — the closest
# generic 'wrong logic' bucket — rather than UNKNOWN, which gives the LLM
# less context.
_ERROR_TYPE_MAP = {
    "SYNTAX": "SYNTAX_ERROR", "INDENT": "SYNTAX_ERROR",
    "IMPORT": "IMPORT_ERROR",
    "TYPE": "TYPE_ERROR",
    "ASSERTION": "ASSERTION_ERROR",
    "FILE_NOT_FOUND": "FILE_NOT_FOUND",
    "ATTRIBUTE": "ATTRIBUTE_ERROR",
    "NAME": "NAME_ERROR",
    "KEY": "KEY_ERROR",
    "INDEX": "INDEX_ERROR",
    "ZERO_DIVISION": "ZERO_DIVISION_ERROR", "DIVISION": "ZERO_DIVISION_ERROR",
}

_FAILED_FILE_RE = re.compile(r"FAILED_FILE:\s*(\S+\.py)")
_ERROR_TYPE_RE = re.compile(r"ERROR_TYPE:\s*(\w+)")
_FILE_CONTENT_RE = re.compile(
    r"FILE_CONTENT_START:[^\n]*\n(.*?)FILE_CONTENT_END",
    re.DOTALL,
)


def extract_failed_files(raw_log: str) -> list[str]:
    """Pull FAILED_FILE: markers from a raw log; deduped, normalised."""
    files: list[str] = []
    if not raw_log:
        return files
    for m in _FAILED_FILE_RE.finditer(raw_log):
        f = m.group(1).strip().lstrip("./")
        if f and f not in files:
            files.append(f)
    return files


def map_error_type(raw_log: str) -> str:
    """Best-effort map raw ERROR_TYPE marker → enum value."""
    m = _ERROR_TYPE_RE.search(raw_log or "")
    if not m:
        return "VALUE_ERROR"
    raw = m.group(1).upper()
    for prefix, mapped in _ERROR_TYPE_MAP.items():
        if raw.startswith(prefix) or prefix in raw:
            return mapped
    return "VALUE_ERROR"


def build_minimal_analysis(raw_log: str) -> dict:
    """Construct a fallback analysis dict when Agent 4 (analyser) is down."""
    files = extract_failed_files(raw_log)
    return {
        "error_type":     map_error_type(raw_log),
        "blast_radius":   "LOW" if len(files) <= 1 else "MEDIUM",
        "affected_files": files,
        "confidence":     0.5,
        "root_cause":     "analyser unavailable — using log-extracted minimal analysis",
    }


def extract_code_from_log(raw_log: str) -> str:
    """Pull the FILE_CONTENT_START..END block from a synthetic log."""
    if not raw_log:
        return ""
    m = _FILE_CONTENT_RE.search(raw_log)
    return m.group(1).strip() if m else ""
