"""Parsers — convert LLM responses into structured patches."""
from __future__ import annotations

import json
import re


def apply_surgical_patch(original: str, changed_lines: dict) -> str:
    """Apply minimal line-level changes to the original file.

    Args:
        original: Original file content (from GitHub).
        changed_lines: ``{"line_number_as_str": "new_line_content"}``,
            line numbers are 1-based to match editor/IDE conventions.

    Returns:
        The patched file content — everything unchanged except the specified lines.

    This is the safest way to apply AI fixes: the LLM cannot hallucinate
    new code outside the explicitly specified lines, guaranteeing minimal diff.
    """
    lines = original.splitlines(keepends=True)
    for line_num_str, new_content in changed_lines.items():
        try:
            idx = int(line_num_str) - 1
        except (ValueError, TypeError):
            continue
        if 0 <= idx < len(lines):
            suffix = "\n" if lines[idx].endswith("\n") else ""
            lines[idx] = new_content.rstrip("\n") + suffix
    return "".join(lines)


class TruncatedResponseError(ValueError):
    """Raised when the LLM response was cut off before JSON was complete."""


def parse_response(response: str) -> dict:
    """Parse JSON from an LLM response.

    Accepts bare JSON or JSON wrapped in a markdown code block.
    Raises TruncatedResponseError when the response looks cut off mid-JSON
    so the caller can retry with a higher token limit.
    """
    try:
        return dict(json.loads(response))
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
    if match:
        try:
            return dict(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass

    # Detect truncation: response starts with '{' but never closes it.
    stripped = response.strip()
    if stripped.startswith("{") and not stripped.endswith("}"):
        raise TruncatedResponseError(
            f"LLM response was truncated before JSON closed: {response[:200]!r}"
        )

    raise ValueError(f"Could not parse LLM response as JSON: {response[:200]!r}")
