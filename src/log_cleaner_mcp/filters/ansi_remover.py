"""Strip ANSI/VT100 escape sequences from log text."""
from __future__ import annotations

import re

# Full ESC-prefixed CSI sequences: ESC [ ... <letter>
_ANSI_FULL_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-9;]*[A-Za-z]"   # CSI: ESC [ ... <letter>
    r"|"
    r"\][^\x07]*\x07"      # OSC: ESC ] ... BEL
    r"|"
    r"[@-Z\\-_]"           # Fe sequences
    r")"
)

# Bare bracket sequences produced when ESC is stripped by capturing tools
# e.g. "[0m[33m" or "[2;31m" left behind after partial stripping
_ANSI_BARE_RE = re.compile(r"\[[0-9;]*m")


def remove_ansi(text: str) -> str:
    """Return *text* with all ANSI escape sequences removed.

    Handles both properly-escaped sequences (with ESC/\\x1b prefix) and
    bare bracket sequences left by log-capturing tools that strip the ESC byte.
    """
    text = _ANSI_FULL_RE.sub("", text)
    text = _ANSI_BARE_RE.sub("", text)
    return text
