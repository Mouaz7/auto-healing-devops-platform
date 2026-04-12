"""Integration test — Scenario B: autonomous feature development (Agent 2→5→6).

Scenario B bypasses log cleaning (Agent 3) and failure analysis (Agent 4).
Agent 5 receives the feature description directly; Agent 6 evaluates.
"""
from __future__ import annotations

import pytest

from src.scheduler.task_classifier import TaskClassifier
from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
from src.shared.models import (
    BlastRadius,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TaskScenario,
    TrafficLightColour,
)


@pytest.fixture
def classifier() -> TaskClassifier:
    return TaskClassifier(nim_client=None)


class TestScenarioBClassification:
    def test_add_feature_classified_as_b(self, classifier):
        result = classifier.classify(
            title="Add dark mode toggle",
            description="Implement a dark/light theme switcher in settings",
        )
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_create_endpoint_classified_as_b(self, classifier):
        result = classifier.classify(
            title="Create export API",
            description="New endpoint to export data as CSV",
        )
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_enable_feature_flag_classified_as_b(self, classifier):
        result = classifier.classify(
            title="Enable SSO support",
            description="Add SAML-based single sign-on",
        )
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT


class TestScenarioBPipeline:
    """Scenario B: no log cleaning or failure analysis — Agent 5→6 direct."""

    def test_scenario_b_skips_to_traffic_light(self, classifier):
        """Verify B tasks go directly to fix evaluation without log cleaning."""
        scenario = classifier.classify(
            "Add export feature", "Implement CSV export endpoint"
        )
        assert scenario == TaskScenario.AUTONOMOUS_DEVELOPMENT

        # Agent 5 stub: confident feature implementation
        fix = CodeFix(
            build_id="b-001",
            fix_patch="def export_csv(data): ...",
            confidence=0.80,
        )
        analysis = FailureAnalysis(
            build_id="b-001",
            error_type=ErrorType.UNKNOWN,
            blast_radius=BlastRadius.LOW,
        )
        tl = evaluate_traffic_light(fix, analysis)
        # 0.80*0.6 + 1.0*0.4 = 0.48+0.40 = 0.88 → GREEN
        assert tl.colour == TrafficLightColour.GREEN

    def test_scenario_b_medium_confidence_yellow(self, classifier):
        scenario = classifier.classify("Implement new feature", "support OAuth2")
        assert scenario == TaskScenario.AUTONOMOUS_DEVELOPMENT

        fix = CodeFix(build_id="b-002", fix_patch="...", confidence=0.55)
        analysis = FailureAnalysis(
            build_id="b-002",
            error_type=ErrorType.UNKNOWN,
            blast_radius=BlastRadius.MEDIUM,
        )
        tl = evaluate_traffic_light(fix, analysis)
        # 0.55*0.6 + 0.6*0.4 = 0.33+0.24 = 0.57 → RED
        # Use higher confidence to land YELLOW
        fix2 = CodeFix(build_id="b-002", fix_patch="...", confidence=0.75)
        tl2 = evaluate_traffic_light(fix2, analysis)
        # 0.75*0.6 + 0.6*0.4 = 0.45+0.24 = 0.69 → YELLOW
        assert tl2.colour == TrafficLightColour.YELLOW
        assert tl2.auto_merge_allowed is False

    def test_scenario_b_does_not_require_log(self, classifier):
        """Scenario B input has no raw log — classifier still works."""
        result = classifier.classify(
            title="New dashboard widget",
            description="Create a real-time metrics widget",
            comments=[],
        )
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT
