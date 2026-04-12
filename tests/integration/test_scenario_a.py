"""Integration test — Scenario A: bug fix pipeline Agent 2→3→4→5→6.

Tests the full classification → clean → analyse → fix → notify chain
using pure-Python components (no real HTTP, no LLM).
"""
from __future__ import annotations

import pytest

from src.scheduler.task_classifier import TaskClassifier
from src.log_cleaner_mcp.pipeline import LogCleaningPipeline
from src.knowledge_graph_mcp.failure_analyser import FailureAnalyser
from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
from src.shared.models import (
    BlastRadius,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TaskScenario,
    TrafficLightColour,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def classifier() -> TaskClassifier:
    return TaskClassifier(nim_client=None)


@pytest.fixture
def cleaner() -> LogCleaningPipeline:
    return LogCleaningPipeline(nim_client=None)


@pytest.fixture
def analyser() -> FailureAnalyser:
    return FailureAnalyser(nim_client=None)


# ---------------------------------------------------------------------------
# Scenario A — bug fix
# ---------------------------------------------------------------------------

class TestScenarioAClassification:
    def test_import_error_issue_classified_as_a(self, classifier):
        result = classifier.classify(
            title="CI failure: ImportError",
            description="ImportError: cannot import name Foo from lib",
        )
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_traceback_in_comment_classified_as_a(self, classifier):
        result = classifier.classify(
            title="Build broken",
            description="",
            comments=['File "src/app.py", line 3\nSyntaxError: invalid syntax'],
        )
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_crash_report_classified_as_a(self, classifier):
        result = classifier.classify(
            title="App crash on deploy",
            description="AttributeError raised at startup",
        )
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT


class TestScenarioAFullPipeline:
    RAW_LOG = (
        "\x1b[31m[ERROR]\x1b[0m Build failed\n"
        "DEBUG init\n"
        "DEBUG connecting\n"
        "ImportError: cannot import name 'Foo'\n"
        '  File "src/app.py", line 3, in <module>\n'
        "    from lib import Foo\n"
    )

    def test_classifier_then_cleaner(self, classifier, cleaner):
        scenario = classifier.classify("ImportError in build", self.RAW_LOG)
        assert scenario == TaskScenario.BUG_FIX_FROM_COMMENT

        clean = cleaner.clean(self.RAW_LOG)
        assert "ImportError" in clean.cleaned_text
        assert "\x1b" not in clean.cleaned_text

    def test_cleaner_then_analyser(self, cleaner, analyser):
        clean = cleaner.clean(self.RAW_LOG)
        analysis = analyser.analyse(clean.cleaned_text, build_id="a-001")
        assert analysis.error_type == ErrorType.IMPORT_ERROR

    def test_full_scenario_a_green(self, classifier, cleaner, analyser):
        """Agent 2 → 3 → 4 → traffic light with high-confidence fix."""
        scenario = classifier.classify("ImportError failure", self.RAW_LOG)
        assert scenario == TaskScenario.BUG_FIX_FROM_COMMENT

        clean = cleaner.clean(self.RAW_LOG)
        analysis = analyser.analyse(clean.cleaned_text, build_id="a-002")

        fix = CodeFix(build_id="a-002", fix_patch="from lib import Foo", confidence=0.92)
        override = FailureAnalysis(
            build_id="a-002",
            error_type=analysis.error_type,
            blast_radius=BlastRadius.LOW,
        )
        tl = evaluate_traffic_light(fix, override)
        assert tl.colour == TrafficLightColour.GREEN
        assert tl.auto_merge_allowed is True

    def test_full_scenario_a_red_high_blast(self, classifier, cleaner, analyser):
        """HIGH blast radius always → RED regardless of confidence."""
        clean = cleaner.clean(self.RAW_LOG)
        analysis = analyser.analyse(clean.cleaned_text, build_id="a-003")

        fix = CodeFix(build_id="a-003", fix_patch="fix", confidence=1.0)
        override = FailureAnalysis(
            build_id="a-003",
            error_type=analysis.error_type,
            blast_radius=BlastRadius.HIGH,
        )
        tl = evaluate_traffic_light(fix, override)
        assert tl.colour == TrafficLightColour.RED
        assert tl.safety_override is True
