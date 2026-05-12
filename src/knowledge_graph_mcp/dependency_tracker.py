"""Dependency tracker for Agent 4 — estimates blast radius from file dependencies.

Sprint 3 provides structural logic (max depth=5, circular import guard,
critical path detection). Full AST-based import parsing is a Sprint 4 concern.
"""
from __future__ import annotations

from src.shared.models import BlastRadius

MAX_DEPTH = 5

_CRITICAL_PATHS = frozenset({
    "config/", "__init__.py", "setup.py", "pyproject.toml", "tests/",
})


class DependencyTracker:
    """Track file dependencies and calculate blast radius.

    Sprint 3 stub: ``get_dependency_chain`` returns a flat list without
    parsing real imports. Sprint 4 will replace the body with AST analysis.
    """

    def get_dependency_chain(
        self,
        file_path: str,
        depth: int = 0,
        visited: set[str] | None = None,
    ) -> list[str]:
        """Return the dependency chain starting at *file_path*.

        Args:
            file_path: Starting file.
            depth: Current recursion depth (caller should leave at default).
            visited: Mutable set of already-visited paths (circular import guard).

        Returns:
            List of file paths in dependency order, including *file_path*.
        """
        if visited is None:
            visited = set()
        if depth >= MAX_DEPTH or file_path in visited:
            return []
        visited.add(file_path)
        # Sprint 3 stub — Sprint 4 will parse actual import statements
        return [file_path]

    def calculate_blast_radius(self, affected_files: list[str]) -> BlastRadius:
        """Classify blast radius from the affected file list.

        Rules:
        - Any critical infrastructure file (config/, __init__.py, setup.py,
          pyproject.toml, tests/) → HIGH (always needs manual review)
        - 6+ files → HIGH (sweeping change, human should review)
        - 2–5 files → MEDIUM (multi-file fix, flags YELLOW)
        - 0–1 files → LOW (typical bug fix)
        """
        count = len(affected_files)
        has_critical = any(
            any(cp in f for cp in _CRITICAL_PATHS)
            for f in affected_files
        )
        if has_critical or count >= 6:
            return BlastRadius.HIGH
        if count >= 2:
            return BlastRadius.MEDIUM
        return BlastRadius.LOW
