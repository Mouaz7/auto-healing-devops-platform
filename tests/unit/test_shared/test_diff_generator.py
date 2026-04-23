"""Unit tests for src.shared.diff_generator."""
from __future__ import annotations

import pytest

from src.shared.diff_generator import (
    DiffResult,
    format_diff_for_slack,
    generate_diff,
    generate_multi_file_diff,
)


class TestGenerateDiff:
    def test_identical_content_produces_empty_diff(self):
        code = "def foo():\n    return 1\n"
        result = generate_diff(code, code, "foo.py")
        assert result.is_empty
        assert result.added_lines == 0
        assert result.removed_lines == 0
        assert result.changed_files == []

    def test_added_line_counted(self):
        original = "def foo():\n    pass\n"
        fixed    = "def foo():\n    pass\n    return 1\n"
        result = generate_diff(original, fixed, "foo.py")
        assert result.added_lines >= 1
        assert result.removed_lines == 0
        assert "foo.py" in result.changed_files

    def test_removed_line_counted(self):
        original = "def foo():\n    x = 1\n    return x\n"
        fixed    = "def foo():\n    return 1\n"
        result = generate_diff(original, fixed, "foo.py")
        assert result.removed_lines >= 1

    def test_changed_line_counted_as_add_and_remove(self):
        original = "assert 1 == 2\n"
        fixed    = "assert 1 == 1\n"
        result = generate_diff(original, fixed, "test.py")
        assert result.added_lines >= 1
        assert result.removed_lines >= 1

    def test_diff_contains_file_headers(self):
        original = "a = 1\n"
        fixed    = "a = 2\n"
        result = generate_diff(original, fixed, "src/config.py")
        assert "a/src/config.py" in result.unified_diff
        assert "b/src/config.py" in result.unified_diff

    def test_summary_describes_changes(self):
        original = "x = 1\n"
        fixed    = "x = 2\n"
        result = generate_diff(original, fixed, "x.py")
        assert "+" in result.summary and "-" in result.summary

    def test_is_empty_true_for_no_changes(self):
        result = generate_diff("same\n", "same\n", "f.py")
        assert result.is_empty

    def test_is_empty_false_for_changes(self):
        result = generate_diff("old\n", "new\n", "f.py")
        assert not result.is_empty


class TestGenerateMultiFileDiff:
    def test_combines_multiple_files(self):
        pairs = [
            ("a = 1\n", "a = 2\n", "src/a.py"),
            ("b = 1\n", "b = 2\n", "src/b.py"),
        ]
        result = generate_multi_file_diff(pairs)
        assert "src/a.py" in result.changed_files
        assert "src/b.py" in result.changed_files
        assert result.added_lines == 2
        assert result.removed_lines == 2

    def test_skips_unchanged_files(self):
        pairs = [
            ("same\n", "same\n", "src/unchanged.py"),
            ("old\n", "new\n", "src/changed.py"),
        ]
        result = generate_multi_file_diff(pairs)
        assert "src/unchanged.py" not in result.changed_files
        assert "src/changed.py" in result.changed_files

    def test_empty_pairs(self):
        result = generate_multi_file_diff([])
        assert result.is_empty


class TestFormatDiffForSlack:
    def test_empty_diff_returns_placeholder(self):
        diff = DiffResult(unified_diff="", added_lines=0, removed_lines=0, changed_files=[])
        text = format_diff_for_slack(diff)
        assert "No changes" in text

    def test_non_empty_diff_contains_summary(self):
        diff = DiffResult(
            unified_diff="--- a/foo.py\n+++ b/foo.py\n-old\n+new\n",
            added_lines=1,
            removed_lines=1,
            changed_files=["foo.py"],
        )
        text = format_diff_for_slack(diff)
        assert "Patch summary" in text
        assert "```" in text

    def test_truncates_at_max_chars(self):
        long_diff = "+" + "x" * 5000
        diff = DiffResult(
            unified_diff=long_diff,
            added_lines=1,
            removed_lines=0,
            changed_files=["big.py"],
        )
        text = format_diff_for_slack(diff, max_chars=1000)
        assert len(text) <= 1000
        assert "truncated" in text
