"""Edge case tests for Log Cleaner (Agent 3)."""
from __future__ import annotations

import pytest

from src.log_cleaner_mcp.pipeline import LogCleaningPipeline


@pytest.fixture
def cleaner() -> LogCleaningPipeline:
    return LogCleaningPipeline(nim_client=None)


class TestEdgeCases:
    def test_empty_log(self, cleaner):
        """Empty string → empty output, reduction_ratio=1.0."""
        result = cleaner.clean("")
        assert result.cleaned_text == ""
        assert result.original_lines == 0
        assert result.reduction_ratio == 1.0

    def test_only_ansi_codes(self, cleaner):
        """Log containing only ANSI escape codes → stripped to empty."""
        raw = "\x1b[31m\x1b[0m\x1b[32m\x1b[0m\n\x1b[33mWARN\x1b[0m\n"
        result = cleaner.clean(raw)
        assert "\x1b" not in result.cleaned_text

    def test_log_without_timestamps(self, cleaner):
        """Logs without timestamps are still cleaned by noise filter."""
        raw = (
            "DEBUG initialising\n"
            "DEBUG connecting to DB\n"
            "ImportError: cannot import name 'Foo'\n"
            '  File "src/app.py", line 3\n'
        )
        result = cleaner.clean(raw)
        assert "ImportError" in result.cleaned_text
        assert result.reduction_ratio >= 0.0

    def test_very_long_log(self, cleaner):
        """100 000-line log doesn't crash, high reduction ratio."""
        noise = "DEBUG connecting\n" * 99_000
        errors = "ImportError: cannot import name 'Foo'\n" * 1_000
        raw = noise + errors
        result = cleaner.clean(raw)
        assert "ImportError" in result.cleaned_text
        assert result.reduction_ratio > 0.5

    def test_java_stack_trace_preserved(self, cleaner):
        """Java-style stack trace lines are preserved."""
        raw = (
            "INFO starting\n"
            "DEBUG init\n"
            "Exception in thread \"main\" java.lang.NullPointerException\n"
            "\tat com.example.Main.run(Main.java:42)\n"
            "\tat com.example.App.start(App.java:10)\n"
        )
        result = cleaner.clean(raw)
        assert "NullPointerException" in result.cleaned_text

    def test_single_error_line(self, cleaner):
        """Single error line → preserved, no crash."""
        result = cleaner.clean("ERROR: something went wrong")
        assert result.original_lines == 1

    def test_only_debug_lines_reduced(self, cleaner):
        """Log with only DEBUG lines → high reduction."""
        raw = "\n".join(f"DEBUG step {i}" for i in range(100))
        result = cleaner.clean(raw)
        assert result.reduction_ratio > 0.0

    def test_unicode_content(self, cleaner):
        """Logs with unicode characters don't crash."""
        raw = "ERROR: Felmeddelande på svenska: 'Åäö kunde inte importeras'\n"
        result = cleaner.clean(raw)
        assert result.original_lines == 1
