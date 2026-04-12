"""Extract and preserve stack traces / exception blocks from logs."""
from __future__ import annotations

import re

# Patterns that signal the *start* of a stack trace or exception block
_EXCEPTION_START = re.compile(
    r"(?:"
    r"Traceback \(most recent call last\)"       # Python
    r"|(?:Exception|Error|Caused by):\s"          # Java / generic
    r"|\bException in thread\b"                   # Java thread exception
    r"|\bFATAL\b"                                  # fatal errors
    r"|\bPANIC\b"                                  # Go / Rust panic
    r")",
    re.IGNORECASE,
)

# Patterns that indicate we're *inside* a stack frame
_FRAME_LINE = re.compile(
    r"(?:"
    r"^\s+at\s+[\w.$<>]+\("                       # Java: at com.example.Foo(Bar.java:42)
    r"|^\s+File \"[^\"]+\",\s+line\s+\d+"         # Python: File "x.py", line N
    r"|^\s+in\s+\w+"                              # Python: in function_name
    r"|^\s+\.\.\.\s+\d+\s+more"                   # Java: ... N more
    r")"
)


def extract_relevant_lines(text: str) -> str:
    """Alias for extract_stack_traces — matches spec function name."""
    return extract_stack_traces(text)


def extract_stack_traces(text: str) -> str:
    """Return only lines that are part of exception/stack trace blocks.

    Lines not belonging to any exception block are dropped unless they
    immediately follow an exception-start line (context preservation).
    """
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_block = False

    for line in lines:
        stripped = line.rstrip("\n")
        if _EXCEPTION_START.search(stripped):
            in_block = True
            result.append(line)
        elif in_block and (_FRAME_LINE.match(stripped) or stripped.startswith("\t")):
            result.append(line)
        else:
            in_block = False

    return "".join(result)
