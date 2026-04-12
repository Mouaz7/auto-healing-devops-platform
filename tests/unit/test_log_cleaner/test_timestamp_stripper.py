from __future__ import annotations

from src.log_cleaner_mcp.filters.timestamp_stripper import strip_timestamps


class TestStripTimestamps:
    def test_strips_iso8601_with_z(self):
        line = "2024-01-15T10:00:01.456Z ERROR: ImportError\n"
        result = strip_timestamps(line)
        assert "2024" not in result
        assert "ERROR: ImportError" in result

    def test_strips_iso8601_with_offset(self):
        line = "2024-01-15T10:00:00+00:00 Build started\n"
        result = strip_timestamps(line)
        assert "Build started" in result
        assert "2024" not in result

    def test_strips_log4j_style(self):
        line = "2024-01-15 10:30:45,123 [ERROR] Something failed\n"
        result = strip_timestamps(line)
        assert "[ERROR] Something failed" in result
        assert "2024" not in result

    def test_preserves_non_timestamp_lines(self):
        line = "ERROR: this is an error\n"
        assert strip_timestamps(line) == line

    def test_multiline_mixed(self, timestamped_log):
        result = strip_timestamps(timestamped_log)
        assert "Build started" in result
        assert "ImportError" in result
        # timestamps removed
        assert "2024-01-15" not in result

    def test_empty_string(self):
        assert strip_timestamps("") == ""

    def test_time_only_stripped(self):
        line = "10:30:45.123 DEBUG something\n"
        result = strip_timestamps(line)
        assert "DEBUG something" in result
        assert "10:30" not in result
