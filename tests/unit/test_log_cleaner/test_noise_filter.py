from __future__ import annotations

from src.log_cleaner_mcp.filters.noise_filter import filter_noise


class TestFilterNoise:
    def test_removes_debug_lines(self):
        text = "DEBUG: initialising connection\nERROR: failed\n"
        result = filter_noise(text)
        assert "DEBUG" not in result
        assert "ERROR: failed" in result

    def test_removes_trace_lines(self):
        text = "TRACE method enter\nActual error\n"
        result = filter_noise(text)
        assert "TRACE" not in result
        assert "Actual error" in result

    def test_removes_blank_lines(self):
        text = "line1\n\n\nline2\n"
        result = filter_noise(text)
        assert "\n\n" not in result

    def test_removes_download_progress(self):
        text = "Downloading https://repo.maven.apache.org/artifact.jar\nERROR\n"
        result = filter_noise(text)
        assert "Downloading" not in result
        assert "ERROR" in result

    def test_keeps_error_lines(self):
        text = "ERROR: ImportError: cannot import name Foo\n"
        assert "ERROR" in filter_noise(text)

    def test_removes_npm_verbose(self):
        text = "npm verb lifecycle\nERROR something\n"
        result = filter_noise(text)
        assert "verb" not in result
        assert "ERROR something" in result

    def test_noisy_log_fixture(self, noisy_log):
        result = filter_noise(noisy_log)
        assert "ERROR: ImportError" in result
        assert "Traceback" in result
        # noise removed
        assert "Download" not in result
