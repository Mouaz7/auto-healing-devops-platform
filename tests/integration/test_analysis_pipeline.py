"""Integration test: full analysis pipeline — Agent 3 → 4 → 5 → 6.

Three end-to-end scenarios exercising the pure-Python pipeline without
any HTTP calls or real LLM invocations. All external dependencies (NIM
client, webhooks) are stubbed.
"""
from __future__ import annotations

import pytest

from src.log_cleaner_mcp.pipeline import LogCleaningPipeline
from src.knowledge_graph_mcp.failure_analyser import FailureAnalyser
from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
from src.shared.models import (
    BlastRadius,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TrafficLightColour,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cleaner() -> LogCleaningPipeline:
    """Log-cleaning pipeline with LLM disabled."""
    return LogCleaningPipeline(nim_client=None)


@pytest.fixture
def analyser() -> FailureAnalyser:
    """Failure analyser with LLM disabled (falls back to regex only)."""
    return FailureAnalyser(nim_client=None)


# ---------------------------------------------------------------------------
# Scenario A — GREEN: high-confidence single-file import error
# ---------------------------------------------------------------------------

class TestGreenScenario:
    """High confidence + LOW blast radius → GREEN + auto_merge_allowed."""

    RAW_LOG = (
        "\x1b[31m[ERROR]\x1b[0m Build failed\n"
        "2024-01-15T10:00:00Z DEBUG init\n"
        "2024-01-15T10:00:00Z DEBUG connecting\n"
        "Traceback (most recent call last):\n"
        '  File "src/app.py", line 3, in <module>\n'
        "    from lib import Foo\n"
        "ImportError: cannot import name 'Foo'\n"
    )

    def test_clean_removes_noise(self, cleaner):
        result = cleaner.clean(self.RAW_LOG)
        assert result.cleaned_lines < result.original_lines
        assert "ImportError" in result.cleaned_text
        assert "\x1b" not in result.cleaned_text

    def test_analyser_detects_import_error(self, analyser):
        result = analyser.analyse(
            "ImportError: cannot import name 'Foo'\n"
            "  File \"src/app.py\", line 3",
            build_id="green-001",
        )
        assert result.error_type == ErrorType.IMPORT_ERROR

    def test_traffic_light_green(self):
        fix = CodeFix(build_id="green-001", fix_patch="diff", confidence=0.95)
        analysis = FailureAnalysis(
            build_id="green-001",
            error_type=ErrorType.IMPORT_ERROR,
            blast_radius=BlastRadius.LOW,
        )
        result = evaluate_traffic_light(fix, analysis)
        # score = 0.95*0.6 + 1.0*0.4 = 0.97 → GREEN
        assert result.colour == TrafficLightColour.GREEN
        assert result.auto_merge_allowed is True
        assert result.safety_override is False

    def test_full_pipeline_green(self, cleaner, analyser):
        clean_result = cleaner.clean(self.RAW_LOG)
        analysis = analyser.analyse(clean_result.cleaned_text, build_id="green-001")

        fix = CodeFix(build_id="green-001", fix_patch="diff", confidence=0.95)
        override_analysis = FailureAnalysis(
            build_id="green-001",
            error_type=analysis.error_type,
            blast_radius=BlastRadius.LOW,
        )
        tl = evaluate_traffic_light(fix, override_analysis)

        assert tl.colour == TrafficLightColour.GREEN
        assert tl.final_score >= 0.85


# ---------------------------------------------------------------------------
# Scenario B — YELLOW: medium confidence, medium blast radius
# ---------------------------------------------------------------------------

class TestYellowScenario:
    """Medium confidence + MEDIUM blast radius → YELLOW, no auto-merge."""

    RAW_LOG = (
        "ERROR TypeError: unsupported operand type(s) for +: 'int' and 'str'\n"
        "  File \"src/utils/calc.py\", line 42, in add\n"
        "  File \"src/api/views.py\", line 10, in handler\n"
        "  File \"tests/test_calc.py\", line 5, in test_add\n"
    )

    def test_traffic_light_yellow(self):
        fix = CodeFix(build_id="yellow-001", fix_patch="diff", confidence=0.55)
        analysis = FailureAnalysis(
            build_id="yellow-001",
            error_type=ErrorType.TYPE_ERROR,
            blast_radius=BlastRadius.MEDIUM,
        )
        result = evaluate_traffic_light(fix, analysis)
        # score = 0.55*0.6 + 0.6*0.4 = 0.33+0.24 = 0.57 → RED
        # Use higher confidence to land in YELLOW
        fix2 = CodeFix(build_id="yellow-001", fix_patch="diff", confidence=0.75)
        result2 = evaluate_traffic_light(fix2, analysis)
        # score = 0.75*0.6 + 0.6*0.4 = 0.45+0.24 = 0.69 → YELLOW
        assert result2.colour == TrafficLightColour.YELLOW
        assert result2.auto_merge_allowed is False

    def test_analyser_detects_type_error(self, analyser):
        result = analyser.analyse(self.RAW_LOG, build_id="yellow-001")
        assert result.error_type == ErrorType.TYPE_ERROR

    def test_full_pipeline_yellow(self, cleaner, analyser):
        clean_result = cleaner.clean(self.RAW_LOG)
        analysis = analyser.analyse(clean_result.cleaned_text, build_id="yellow-001")

        fix = CodeFix(build_id="yellow-001", fix_patch="diff", confidence=0.75)
        override_analysis = FailureAnalysis(
            build_id="yellow-001",
            error_type=analysis.error_type,
            blast_radius=BlastRadius.MEDIUM,
        )
        tl = evaluate_traffic_light(fix, override_analysis)

        assert tl.colour == TrafficLightColour.YELLOW
        assert 0.60 <= tl.final_score < 0.85


# ---------------------------------------------------------------------------
# Scenario C — RED: high blast radius safety override
# ---------------------------------------------------------------------------

class TestRedScenario:
    """HIGH blast radius always forces RED regardless of confidence."""

    RAW_LOG = (
        "SyntaxError: invalid syntax\n"
        "  File \"src/core/__init__.py\", line 1\n"
        "  File \"config/settings.py\", line 5\n"
        "  File \"tests/conftest.py\", line 2\n"
        "  File \"setup.py\", line 3\n"
        "  File \"src/api/routes.py\", line 7\n"
        "  File \"src/models/user.py\", line 12\n"
    )

    def test_traffic_light_red_safety_override(self):
        fix = CodeFix(build_id="red-001", fix_patch="diff", confidence=1.0)
        analysis = FailureAnalysis(
            build_id="red-001",
            error_type=ErrorType.SYNTAX_ERROR,
            blast_radius=BlastRadius.HIGH,
        )
        result = evaluate_traffic_light(fix, analysis)
        assert result.colour == TrafficLightColour.RED
        assert result.safety_override is True
        assert result.auto_merge_allowed is False

    def test_traffic_light_red_low_confidence(self):
        fix = CodeFix(build_id="red-002", fix_patch="diff", confidence=0.1)
        analysis = FailureAnalysis(
            build_id="red-002",
            error_type=ErrorType.SYNTAX_ERROR,
            blast_radius=BlastRadius.LOW,
        )
        result = evaluate_traffic_light(fix, analysis)
        # score = 0.1*0.6 + 1.0*0.4 = 0.46 → RED
        assert result.colour == TrafficLightColour.RED
        assert result.safety_override is False

    def test_analyser_detects_syntax_error(self, analyser):
        result = analyser.analyse(self.RAW_LOG, build_id="red-001")
        assert result.error_type == ErrorType.SYNTAX_ERROR

    def test_full_pipeline_red_blast_radius(self, cleaner, analyser):
        clean_result = cleaner.clean(self.RAW_LOG)
        analysis = analyser.analyse(clean_result.cleaned_text, build_id="red-001")

        fix = CodeFix(build_id="red-001", fix_patch="diff", confidence=0.95)
        override_analysis = FailureAnalysis(
            build_id="red-001",
            error_type=analysis.error_type,
            blast_radius=BlastRadius.HIGH,
        )
        tl = evaluate_traffic_light(fix, override_analysis)

        assert tl.colour == TrafficLightColour.RED
        assert tl.safety_override is True
