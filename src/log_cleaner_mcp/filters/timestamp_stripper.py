"""Strip timestamps from the beginning of log lines."""
from __future__ import annotations

import re

# Ordered from most specific to least specific to avoid partial matches
_PATTERNS: list[re.Pattern[str]] = [
    # ISO-8601 with time and optional fractional seconds + timezone
    # e.g. 2024-01-15T10:30:45.123+00:00  or  2024-01-15T10:30:45Z
    re.compile(
        r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
        r"(?:[.,]\d+)?"
        r"(?:Z|[+-]\d{2}:?\d{2})?\s*"
    ),
    # Log4j style: 2024-01-15 10:30:45,123
    re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.:]\d+\s*"),
    # Bracketed timestamps: [2024-01-15 10:30:45]
    re.compile(r"^\[\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]\s*"),
    # Unix epoch seconds/milliseconds at line start: 1705312245 or 1705312245123
    re.compile(r"^\d{10,13}\s+"),
    # Time only: 10:30:45.123 or 10:30:45
    re.compile(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"),
]


def strip_timestamps(text: str) -> str:
    """Remove leading timestamps from each line of *text*."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        for pattern in _PATTERNS:
            stripped = pattern.sub("", line)
            if stripped != line:
                line = stripped
                break
        result.append(line)
    return "".join(result)
