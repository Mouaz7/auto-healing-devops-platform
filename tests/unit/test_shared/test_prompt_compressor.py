"""Unit tests for src.shared.prompt_compressor."""
from __future__ import annotations

import pytest

from src.shared.prompt_compressor import compress_log, compression_ratio


class TestCompressLog:
    def test_short_log_unchanged(self):
        log = "FAILED tests/test_foo.py::test_bar\nAssertionError: assert 1 == 2\n"
        result = compress_log(log, max_chars=3000)
        assert result == log

    def test_output_within_max_chars(self):
        big_log = "\n".join(f"line {i}" for i in range(5000))
        result = compress_log(big_log, max_chars=3000)
        assert len(result) <= 3000

    def test_error_lines_preserved(self):
        noise  = "\n".join(["Downloading package... 50%"] * 200)
        signal = "\nFAILED tests/test_sample.py::test_calc\nAssertionError: assert 1 == 2\n"
        log = noise + signal
        result = compress_log(log, max_chars=3000)
        assert "AssertionError" in result

    def test_traceback_lines_preserved(self):
        log = (
            "\n".join(["."] * 300)
            + '\nTraceback (most recent call last):\n'
            + '  File "src/foo.py", line 42, in bar\n'
            + "    raise ValueError\n"
        )
        result = compress_log(log, max_chars=3000)
        assert "Traceback" in result

    def test_head_and_tail_preserved(self):
        lines = [f"line{i}" for i in range(100)]
        log = "\n".join(lines)
        result = compress_log(log, max_chars=3000)
        assert "line0" in result
        assert "line99" in result

    def test_omission_marker_present_when_lines_dropped(self):
        big_log = "\n".join(["noise line x"] * 500)
        result = compress_log(big_log, max_chars=500)
        assert "omitted" in result or len(result) <= 500

    def test_empty_log(self):
        result = compress_log("", max_chars=1000)
        assert result == ""

    def test_already_small_log_not_modified(self):
        log = "ERROR: something went wrong\n"
        result = compress_log(log, max_chars=1000)
        assert result == log


class TestCompressionRatio:
    def test_full_retention(self):
        log = "short log"
        compressed = log
        assert compression_ratio(log, compressed) == pytest.approx(1.0)

    def test_partial_retention(self):
        original = "a" * 1000
        compressed = "a" * 100
        assert compression_ratio(original, compressed) == pytest.approx(0.1)

    def test_empty_original(self):
        assert compression_ratio("", "anything") == 1.0
