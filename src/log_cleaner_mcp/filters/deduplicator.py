"""Collapse consecutive duplicate or near-duplicate log lines."""
from __future__ import annotations

import re

# Tokens that vary between otherwise identical repeated lines
_VARIABLE_TOKENS = re.compile(
    r"(?:"
    r"0x[0-9a-fA-F]+"                  # hex addresses
    r"|\b\d{4}-\d{2}-\d{2}\b"          # dates
    r"|\b\d{2}:\d{2}:\d{2}\b"          # times
    r"|\b\d{10,13}\b"                  # unix timestamps
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-"     # UUIDs
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    r"|\b\d+\.\d+\.\d+\b"              # version numbers / IPs
    r"|\b\d+ms\b"                      # durations
    r"|\s+\d+\s"                       # isolated numbers
    r")"
)

_MIN_LINE_LEN = 10  # only normalise non-trivial lines


def _normalise(line: str) -> str:
    """Replace variable tokens with a placeholder for similarity comparison."""
    if len(line) < _MIN_LINE_LEN:
        return line
    return _VARIABLE_TOKENS.sub("§", line)


def deduplicate(text: str, max_repeats: int = 3) -> str:
    """Collapse runs of duplicate/near-duplicate lines.

    A run of more than *max_repeats* identical normalised lines is
    replaced by the first occurrence plus a ``[repeated N times]`` summary.
    """
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        norm = _normalise(current.rstrip("\n"))
        j = i + 1
        while j < len(lines) and _normalise(lines[j].rstrip("\n")) == norm:
            j += 1
        run = j - i
        if run > max_repeats:
            result.append(current)
            result.append(f"    [repeated {run - 1} more time{'s' if run > 2 else ''}]\n")
        else:
            result.extend(lines[i:j])
        i = j
    return "".join(result)
