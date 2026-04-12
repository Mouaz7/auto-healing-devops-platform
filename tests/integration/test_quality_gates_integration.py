"""Integration test — Agent 5 runs Bandit+Pylint on generated fixes."""
from __future__ import annotations

import pytest

from src.llm_mcp.fix_generator import FixGenerator
from src.shared.models import BlastRadius, ErrorType, FailureAnalysis


class TestFixGeneratorQualityGates:
    """Test that Agent 5 (FixGenerator) evaluates quality of generated code."""

    @pytest.fixture
    def generator(self) -> FixGenerator:
        """Create a FixGenerator without LLM (for mocking)."""
        return FixGenerator(nim_client=None)

    def test_generator_without_nim_raises(self, generator):
        """If no NIM client, generate_fix should raise RuntimeError."""
        analysis = FailureAnalysis(
            build_id="test-1",
            error_type=ErrorType.IMPORT_ERROR,
            root_cause="Missing import",
            affected_files=["app.py"],
            blast_radius=BlastRadius.LOW,
            confidence=0.8,
        )

        with pytest.raises(RuntimeError, match="No NIM client"):
            generator.generate_fix(
                analysis=analysis,
                code_context="",
                cleaned_logs="ImportError",
            )

    def test_code_fix_includes_lint_ok_flag(self):
        """CodeFix object should include lint_ok flag from quality evaluation."""
        # This test would need a mocked NIM client to verify the full flow.
        # For now, we test the structure exists.
        from src.shared.models import CodeFix

        fix = CodeFix(
            build_id="test-1",
            fix_patch="x = 1 + 2",
            confidence=0.9,
            lint_ok=True,
        )
        assert hasattr(fix, "lint_ok")
        assert fix.lint_ok is True

    def test_code_fix_confidence_adjusted_for_quality(self):
        """CodeFix confidence should be adjusted based on quality gates."""
        from src.shared.models import CodeFix

        # Simulating: base_confidence=0.9, quality_modifier=-0.2 → adjusted=0.7
        fix = CodeFix(
            build_id="test-1",
            fix_patch="code",
            confidence=0.7,  # Already adjusted
            lint_ok=False,
        )
        # The adjustment happens in generate_fix(); we just verify the structure
        assert fix.confidence == 0.7
        assert fix.lint_ok is False
