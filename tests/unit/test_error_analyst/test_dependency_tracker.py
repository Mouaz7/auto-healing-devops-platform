from __future__ import annotations

import pytest

from src.knowledge_graph_mcp.dependency_tracker import DependencyTracker, MAX_DEPTH
from src.shared.models import BlastRadius


@pytest.fixture
def tracker() -> DependencyTracker:
    return DependencyTracker()


class TestGetDependencyChain:
    def test_returns_starting_file(self, tracker):
        chain = tracker.get_dependency_chain("src/main.py")
        assert "src/main.py" in chain

    def test_max_depth_zero_returns_empty(self, tracker):
        chain = tracker.get_dependency_chain("src/main.py", depth=MAX_DEPTH)
        assert chain == []

    def test_visited_prevents_revisit(self, tracker):
        visited: set[str] = {"src/main.py"}
        chain = tracker.get_dependency_chain("src/main.py", visited=visited)
        assert chain == []

    def test_visited_set_updated(self, tracker):
        visited: set[str] = set()
        tracker.get_dependency_chain("src/main.py", visited=visited)
        assert "src/main.py" in visited

    def test_depth_increments_correctly(self, tracker):
        # At depth MAX_DEPTH-1, should still return the file
        chain = tracker.get_dependency_chain("src/a.py", depth=MAX_DEPTH - 1)
        assert "src/a.py" in chain

    def test_independent_calls_dont_share_state(self, tracker):
        chain1 = tracker.get_dependency_chain("src/a.py")
        chain2 = tracker.get_dependency_chain("src/a.py")
        assert chain1 == chain2


class TestCalculateBlastRadius:
    def test_no_files_is_low(self, tracker):
        assert tracker.calculate_blast_radius([]) == BlastRadius.LOW

    def test_one_file_is_low(self, tracker):
        assert tracker.calculate_blast_radius(["src/main.py"]) == BlastRadius.LOW

    def test_two_files_is_medium(self, tracker):
        assert tracker.calculate_blast_radius(["src/a.py", "src/b.py"]) == BlastRadius.MEDIUM

    def test_five_files_is_medium(self, tracker):
        files = [f"src/file{i}.py" for i in range(5)]
        assert tracker.calculate_blast_radius(files) == BlastRadius.MEDIUM

    def test_six_files_is_high(self, tracker):
        files = [f"src/file{i}.py" for i in range(6)]
        assert tracker.calculate_blast_radius(files) == BlastRadius.HIGH

    def test_tests_directory_forces_high(self, tracker):
        assert tracker.calculate_blast_radius(["tests/test_main.py"]) == BlastRadius.HIGH

    def test_config_directory_forces_high(self, tracker):
        assert tracker.calculate_blast_radius(["config/settings.py"]) == BlastRadius.HIGH

    def test_init_file_forces_high(self, tracker):
        assert tracker.calculate_blast_radius(["mypackage/__init__.py"]) == BlastRadius.HIGH

    def test_setup_py_forces_high(self, tracker):
        assert tracker.calculate_blast_radius(["setup.py"]) == BlastRadius.HIGH

    def test_pyproject_forces_high(self, tracker):
        assert tracker.calculate_blast_radius(["pyproject.toml"]) == BlastRadius.HIGH
