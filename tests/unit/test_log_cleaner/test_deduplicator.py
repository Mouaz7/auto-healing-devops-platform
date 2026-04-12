from __future__ import annotations

from src.log_cleaner_mcp.filters.deduplicator import deduplicate


class TestDeduplicate:
    def test_keeps_unique_lines(self):
        text = "line1\nline2\nline3\n"
        assert deduplicate(text) == text

    def test_collapses_long_runs(self):
        # 4 identical lines exceeds max_repeats=3 → should be collapsed
        text = "ERROR: ImportError\n" * 4
        result = deduplicate(text)
        assert "repeated" in result
        assert result.count("ERROR: ImportError") == 1

    def test_keeps_runs_within_max_repeats(self):
        # 3 identical lines with default max_repeats=3 → all kept (≤ threshold)
        text = "same line\nsame line\nsame line\n"
        result = deduplicate(text)
        assert "repeated" not in result
        assert result.count("same line") == 3

    def test_collapses_runs_exceeding_max_repeats(self):
        text = "x\n" * 10
        result = deduplicate(text)
        assert "repeated" in result
        assert result.count("x\n") == 1

    def test_normalises_timestamps_for_comparison(self):
        # Two lines that differ only in timestamp should be treated as duplicates
        text = (
            "2024-01-01 10:00:00 ERROR same message\n"
            "2024-01-01 10:00:01 ERROR same message\n"
            "2024-01-01 10:00:02 ERROR same message\n"
            "2024-01-01 10:00:03 ERROR same message\n"
        )
        result = deduplicate(text)
        assert "repeated" in result

    def test_empty_string(self):
        assert deduplicate("") == ""

    def test_single_line(self):
        text = "single line\n"
        assert deduplicate(text) == text
