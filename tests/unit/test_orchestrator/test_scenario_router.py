"""Unit tests for ScenarioRouter."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.orchestrator_mcp.scenario_router import ScenarioRouter
from src.shared.models import BuildEvent, TaskScenario


@pytest.fixture
def router() -> ScenarioRouter:
    return ScenarioRouter()


def _event(status: str, job_name: str = "ci-build") -> BuildEvent:
    return BuildEvent(
        build_id="b1",
        repo="org/repo",
        branch="main",
        timestamp=datetime.now(timezone.utc),
        job_name=job_name,
        status=status,
    )


class TestRoute:
    def test_failure_status_is_scenario_a(self, router):
        assert router.route(_event("FAILURE")) == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_failure_lowercase_is_scenario_a(self, router):
        assert router.route(_event("failure")) == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_feature_job_name_is_scenario_b(self, router):
        assert router.route(_event("SUCCESS", "new-feature-build")) == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_develop_job_name_is_scenario_b(self, router):
        assert router.route(_event("SUCCESS", "develop-api")) == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_implement_job_name_is_scenario_b(self, router):
        assert router.route(_event("SUCCESS", "implement-oauth")) == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_unrecognised_status_is_yellow(self, router):
        assert router.route(_event("SUCCESS", "ci-build")) == TaskScenario.YELLOW_MANUAL

    def test_empty_status_is_yellow(self, router):
        assert router.route(_event("")) == TaskScenario.YELLOW_MANUAL
