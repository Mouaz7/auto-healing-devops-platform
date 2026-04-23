"""Diff generator — produces unified diffs from original + fixed content.

The diff is:
  1. Stored in the fix record so reviewers see exactly what changed.
  2. Attached to the Slack notification so human reviewers can read the
     patch inline without cloning the branch.
  3. Used as the body of the GitHub PR description for clarity.

Usage:
    from src.shared.diff_generator import generate_diff, DiffResult

    result = generate_diff(
        original="def foo():\n    return 1\n",
        fixed="def foo():\n    return 2\n",
        file_path="src/foo.py",
    )
    print(result.unified_diff)   # classic unified diff text
    print(result.added_lines)    # count of + lines
    print(result.removed_lines)  # count of - lines
    print(result.is_empty)       # True if no changes
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class DiffResult:
    """Result of a diff computation."""

    unified_diff:  str
    added_lines:   int
    removed_lines: int
    changed_files: list[str]

    @property
    def is_empty(self) -> bool:
        return self.added_lines == 0 and self.removed_lines == 0

    @property
    def summary(self) -> str:
        if self.is_empty:
            return "no changes"
        return f"+{self.added_lines} -{self.removed_lines} lines in {len(self.changed_files)} file(s)"


def generate_diff(
    original: str,
    fixed: str,
    file_path: str = "file.py",
    context_lines: int = 3,
) -> DiffResult:
    """Generate a unified diff between *original* and *fixed* content.

    Args:
        original:      Original file content (before fix).
        fixed:         Fixed file content (after fix).
        file_path:     File path shown in the diff header.
        context_lines: Lines of context around each change (default 3).

    Returns:
        :class:`DiffResult` with the diff text and statistics.
    """
    orig_lines  = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        orig_lines,
        fixed_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=context_lines,
    ))

    unified = "".join(diff_lines)
    added   = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return DiffResult(
        unified_diff=unified,
        added_lines=added,
        removed_lines=removed,
        changed_files=[file_path] if unified else [],
    )


def generate_multi_file_diff(
    file_pairs: list[tuple[str, str, str]],
    context_lines: int = 3,
) -> DiffResult:
    """Generate a combined diff for multiple files.

    Args:
        file_pairs: List of (original, fixed, file_path) tuples.
        context_lines: Lines of context per hunk.

    Returns:
        Combined :class:`DiffResult` across all files.
    """
    all_diffs: list[str] = []
    total_added   = 0
    total_removed = 0
    changed: list[str] = []

    for original, fixed, file_path in file_pairs:
        result = generate_diff(original, fixed, file_path, context_lines)
        if not result.is_empty:
            all_diffs.append(result.unified_diff)
            total_added   += result.added_lines
            total_removed += result.removed_lines
            changed.append(file_path)

    return DiffResult(
        unified_diff="\n".join(all_diffs),
        added_lines=total_added,
        removed_lines=total_removed,
        changed_files=changed,
    )


def format_diff_for_slack(diff: DiffResult, max_chars: int = 2800) -> str:
    """Format a diff for inline display in a Slack Block Kit code block.

    Slack has a ~3000 char limit per block — truncates if needed.

    Args:
        diff:      The diff result to format.
        max_chars: Maximum characters to include.

    Returns:
        Formatted string suitable for Slack's ```code``` blocks.
    """
    if diff.is_empty:
        return "_No changes in this patch._"

    header = f"*Patch summary:* {diff.summary}\n"
    body   = diff.unified_diff

    if len(header) + len(body) > max_chars:
        body = body[:max_chars - len(header) - 30] + "\n... (diff truncated)"

    return header + f"```\n{body}```"
