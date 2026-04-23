"""Unit tests for src.shared.task_complexity."""
from __future__ import annotations

import pytest

from src.shared.task_complexity import Complexity, score_complexity


class TestScoreComplexity:
    def test_simple_assertion_low(self):
        level = score_complexity(
            error_type="ASSERTION_ERROR",
            blast_radius="LOW",
            affected_files=["tests/test_foo.py"],
        )
        assert level == Complexity.LOW

    def test_import_error_high_radius_is_high(self):
        level = score_complexity(
            error_type="IMPORT_ERROR",
            blast_radius="HIGH",
            affected_files=["src/a.py", "src/b.py", "src/c.py"],
        )
        assert level == Complexity.HIGH

    def test_many_files_pushes_to_high(self):
        level = score_complexity(
            error_type="ASSERTION_ERROR",
            blast_radius="LOW",
            affected_files=["a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py"],
        )
        assert level == Complexity.HIGH

    def test_medium_complexity(self):
        level = score_complexity(
            error_type="TIMEOUT",
            blast_radius="LOW",
            affected_files=["src/worker.py"],
        )
        assert level == Complexity.MEDIUM

    def test_long_log_adds_points(self):
        long_log = "x" * 1100
        level = score_complexity(
            error_type="ASSERTION_ERROR",
            blast_radius="LOW",
            affected_files=["tests/t.py"],
            log_snippet=long_log,
        )
        # ASSERTION_ERROR(1) + LOW(0) + 1 file(1) + long log(2) = 4 → MEDIUM
        assert level in (Complexity.MEDIUM, Complexity.HIGH)

    def test_verbose_root_cause_adds_point(self):
        long_cause = "A" * 250
        level = score_complexity(
            error_type="ASSERTION_ERROR",
            blast_radius="LOW",
            affected_files=["tests/t.py"],
            root_cause=long_cause,
        )
        # ASSERTION_ERROR(1) + LOW(0) + 1 file(1) + long root_cause(1) = 3 → MEDIUM
        assert level == Complexity.MEDIUM

    def test_empty_files_no_crash(self):
        level = score_complexity(
            error_type="UNKNOWN",
            blast_radius="LOW",
            affected_files=[],
        )
        assert level == Complexity.LOW

    def test_segfault_high_complexity(self):
        level = score_complexity(
            error_type="SEGFAULT",
            blast_radius="MEDIUM",
            affected_files=["src/native.py", "src/ext.py"],
        )
        # 3 + 1 + 2 = 6 → MEDIUM (just below 7)
        assert level in (Complexity.MEDIUM, Complexity.HIGH)
