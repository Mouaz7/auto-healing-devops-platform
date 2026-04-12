"""Edge case tests for Error Analyst (Agent 4)."""
from __future__ import annotations

import pytest

from src.knowledge_graph_mcp.failure_analyser import FailureAnalyser
from src.knowledge_graph_mcp.dependency_tracker import DependencyTracker, MAX_DEPTH
from src.shared.models import BlastRadius, ErrorType


@pytest.fixture
def analyser() -> FailureAnalyser:
    return FailureAnalyser(nim_client=None)


@pytest.fixture
def tracker() -> DependencyTracker:
    return DependencyTracker()


class TestUnknownError:
    def test_unknown_error_type_when_no_match(self, analyser):
        """Log with unrecognised error pattern → UNKNOWN."""
        result = analyser.analyse("Something went wrong at line 5", "b1")
        assert result.error_type == ErrorType.UNKNOWN

    def test_unknown_confidence_is_low(self, analyser):
        """UNKNOWN error type → confidence = 0.3."""
        result = analyser.analyse("Some arbitrary failure message", "b2")
        assert result.confidence == pytest.approx(0.3)

    def test_known_error_confidence_is_high(self, analyser):
        """ImportError → confidence = 0.9."""
        result = analyser.analyse("ImportError: cannot import name 'Foo'", "b3")
        assert result.confidence == pytest.approx(0.9)


class TestCircularImportMaxDepth:
    def test_dependency_chain_stops_at_max_depth(self, tracker):
        """get_dependency_chain stops at MAX_DEPTH=5 to prevent infinite loops."""
        # Simulate recursion at max depth by calling directly at depth=MAX_DEPTH
        result = tracker.get_dependency_chain("src/app.py", depth=MAX_DEPTH)
        assert result == []

    def test_dependency_chain_stops_for_visited(self, tracker):
        """Already-visited files are skipped (circular import guard)."""
        visited = {"src/app.py"}
        result = tracker.get_dependency_chain("src/app.py", visited=visited)
        assert result == []

    def test_max_depth_constant_is_five(self):
        """MAX_DEPTH is 5 as per spec."""
        assert MAX_DEPTH == 5


class TestNoFilesInLogs:
    def test_no_file_paths_in_log(self, analyser):
        """Stack trace without File references → affected_files = []."""
        logs = "ImportError: cannot import name 'Foo'\nNo file paths here"
        result = analyser.analyse(logs, "b4")
        assert result.affected_files == []

    def test_file_paths_extracted_from_traceback(self, analyser):
        """Standard Python traceback file refs are extracted."""
        logs = (
            "ImportError: cannot import 'Foo'\n"
            '  File "src/app.py", line 3, in <module>\n'
            '  File "src/lib.py", line 10, in load\n'
        )
        result = analyser.analyse(logs, "b5")
        assert "src/app.py" in result.affected_files
        assert "src/lib.py" in result.affected_files


class TestMultipleErrorTypes:
    def test_first_pattern_wins(self, analyser):
        """When both ImportError and SyntaxError present, first pattern matched wins."""
        # ERROR_PATTERNS is ordered: ImportError comes before SyntaxError
        logs = (
            "ImportError: cannot import name 'Foo'\n"
            "SyntaxError: invalid syntax\n"
        )
        result = analyser.analyse(logs, "b6")
        assert result.error_type == ErrorType.IMPORT_ERROR

    def test_syntax_error_detected(self, analyser):
        """SyntaxError detected when no ImportError present."""
        result = analyser.analyse("SyntaxError: invalid syntax at line 5", "b7")
        assert result.error_type == ErrorType.SYNTAX_ERROR

    def test_attribute_error_detected(self, analyser):
        """AttributeError detected correctly."""
        result = analyser.analyse("AttributeError: 'NoneType' object has no attribute 'foo'", "b8")
        assert result.error_type == ErrorType.ATTRIBUTE_ERROR


class TestBlastRadiusCalculation:
    def test_zero_files_is_low(self, tracker):
        """No affected files → LOW blast radius."""
        assert tracker.calculate_blast_radius([]) == BlastRadius.LOW

    def test_one_file_is_low(self, tracker):
        """1 file → LOW blast radius."""
        assert tracker.calculate_blast_radius(["src/app.py"]) == BlastRadius.LOW

    def test_two_files_is_medium(self, tracker):
        """2 files → MEDIUM blast radius."""
        assert tracker.calculate_blast_radius(["src/a.py", "src/b.py"]) == BlastRadius.MEDIUM

    def test_six_files_is_high(self, tracker):
        """6+ files → HIGH blast radius."""
        files = [f"src/file{i}.py" for i in range(6)]
        assert tracker.calculate_blast_radius(files) == BlastRadius.HIGH

    def test_critical_path_forces_high(self, tracker):
        """File in tests/ → HIGH regardless of count."""
        assert tracker.calculate_blast_radius(["tests/test_app.py"]) == BlastRadius.HIGH

    def test_init_py_forces_high(self, tracker):
        """__init__.py → HIGH blast radius."""
        assert tracker.calculate_blast_radius(["src/__init__.py"]) == BlastRadius.HIGH
