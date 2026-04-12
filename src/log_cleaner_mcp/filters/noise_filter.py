"""Remove noisy, low-value lines from build logs."""
from __future__ import annotations

import re

# Lines matching any of these patterns are dropped
_NOISE_PATTERNS: list[re.Pattern[str]] = [
    # Debug / trace level log entries
    re.compile(r"^\s*(?:DEBUG|TRACE|VERBOSE)\b", re.IGNORECASE),
    # Download/upload progress with percentage (any format)
    re.compile(r"(?:Download(?:ing)?|Upload(?:ing)?|Progress)[^\n]*\d+%"),
    # Unicode and ASCII progress bars  (━, =, -, #, █)
    re.compile(r"^\s*[━=\-#█]{3,}\s*$"),
    re.compile(r"^\s*[━=\-#█ ]{3,}\d"),              # bar followed by transfer stats
    # Maven/Gradle/pip download lines (with or without URL)
    re.compile(r"^\s*(?:Download(?:ing|ed)|Resolving)\s+"),
    re.compile(r"^\s*Downloading\s+\S+"),
    # pip install noise
    re.compile(r"^\s*(?:Collecting|Using cached|Installing collected|Requirement already|Successfully installed)\b"),
    # Jenkins Pipeline structural lines (low diagnostic value)
    re.compile(r"^\s*\[Pipeline\]"),
    # "Nothing to do" / already cached noise
    re.compile(r"^\s*(?:Nothing to do|Already up[ -]to[ -]date)\.?\s*$", re.IGNORECASE),
    # Blank / whitespace-only lines
    re.compile(r"^\s*$"),
    # Heartbeat / keepalive lines
    re.compile(r"(?:heartbeat|keepalive|ping|pong)", re.IGNORECASE),
    # Gradle daemon / info spam
    re.compile(r"^\s*Daemon\s+\w+\s+(?:started|stopped|idle)", re.IGNORECASE),
    # npm/yarn verbose lines
    re.compile(r"^\s*(?:npm\s+)?(?:verb|silly|http)\s+", re.IGNORECASE),
    # Generic "Running on agent" / workspace lines
    re.compile(r"^\s*Running on .+ in /workspace/"),
]


def filter_noise(text: str) -> str:
    """Remove noisy lines from *text*, returning only signal lines."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = [
        line for line in lines
        if not any(p.search(line.rstrip("\n")) for p in _NOISE_PATTERNS)
    ]
    return "".join(kept)
