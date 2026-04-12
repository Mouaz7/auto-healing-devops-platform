from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.shared.models import (
    BlastRadius,
    BuildEvent,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TaskScenario,
    TrafficLightColour,
    TrafficLightResult,
    WorkflowState,
    WorkflowStatus,
)


class TestEnums:
    def test_traffic_light_colour_values(self):
        assert TrafficLightColour.GREEN == "GREEN"
        assert TrafficLightColour.YELLOW == "YELLOW"
        assert TrafficLightColour.RED == "RED"

    def test_blast_radius_values(self):
        assert BlastRadius.LOW == "LOW"
        assert BlastRadius.MEDIUM == "MEDIUM"
        assert BlastRadius.HIGH == "HIGH"

    def test_workflow_status_all_states(self):
        expected = {
            "PENDING", "ANALYSING", "GENERATING_FIX", "VALIDATING",
            "AWAITING_REVIEW", "APPLYING_FIX", "COMPLETED", "FAILED", "BLOCKED",
        }
        actual = {s.value for s in WorkflowStatus}
        assert actual == expected

    def test_task_scenario_values(self):
        assert TaskScenario.BUG_FIX_FROM_COMMENT == "A"
        assert TaskScenario.AUTONOMOUS_DEVELOPMENT == "B"
        assert TaskScenario.YELLOW_MANUAL == "YELLOW"

    def test_error_type_unknown_exists(self):
        assert ErrorType.UNKNOWN == "UNKNOWN"

    def test_enums_are_strings(self):
        assert isinstance(TrafficLightColour.GREEN, str)
        assert isinstance(BlastRadius.HIGH, str)


class TestBuildEvent:
    def test_creation_with_required_fields(self):
        ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        event = BuildEvent(
            build_id="b-001",
            repo="org/repo",
            branch="main",
            timestamp=ts,
        )
        assert event.build_id == "b-001"
        assert event.repo == "org/repo"
        assert event.branch == "main"
        assert event.timestamp == ts

    def test_defaults(self):
        event = BuildEvent(
            build_id="b-002",
            repo="org/repo",
            branch="main",
            timestamp=datetime.now(timezone.utc),
        )
        assert event.status == "FAILED"
        assert event.job_name == ""
        assert event.log_url == ""


class TestFailureAnalysis:
    def test_creation(self, failure_analysis):
        assert failure_analysis.build_id == "test-001"
        assert failure_analysis.error_type == ErrorType.IMPORT_ERROR
        assert failure_analysis.blast_radius == BlastRadius.LOW
        assert failure_analysis.confidence == 0.90

    def test_affected_files_default_empty(self):
        fa = FailureAnalysis(
            build_id="b-001",
            error_type=ErrorType.UNKNOWN,
            blast_radius=BlastRadius.LOW,
        )
        assert fa.affected_files == []
        assert fa.confidence == 0.0
        assert fa.root_cause == ""

    def test_affected_files_not_shared_between_instances(self):
        fa1 = FailureAnalysis(build_id="a", error_type=ErrorType.UNKNOWN, blast_radius=BlastRadius.LOW)
        fa2 = FailureAnalysis(build_id="b", error_type=ErrorType.UNKNOWN, blast_radius=BlastRadius.LOW)
        fa1.affected_files.append("file.py")
        assert fa2.affected_files == []


class TestCodeFix:
    def test_creation(self, code_fix):
        assert code_fix.build_id == "test-001"
        assert code_fix.confidence == 0.88
        assert code_fix.lint_ok is True
        assert code_fix.test_ok is False

    def test_files_to_modify_default_empty(self):
        fix = CodeFix(build_id="b-001", fix_patch="")
        assert fix.files_to_modify == []


class TestTrafficLightResult:
    def test_green_allows_merge(self, traffic_light_green):
        assert traffic_light_green.colour == TrafficLightColour.GREEN
        assert traffic_light_green.auto_merge_allowed is True
        assert traffic_light_green.final_score >= 0.85

    def test_red_blocks_merge(self, traffic_light_red):
        assert traffic_light_red.colour == TrafficLightColour.RED
        assert traffic_light_red.auto_merge_allowed is False

    def test_safety_override_default_false(self, traffic_light_green):
        assert traffic_light_green.safety_override is False

    def test_high_blast_radius_safety_override(self):
        result = TrafficLightResult(
            build_id="b-001",
            colour=TrafficLightColour.RED,
            final_score=0.90,
            auto_merge_allowed=False,
            reason="HIGH blast radius forced RED",
            blast_radius=BlastRadius.HIGH,
            safety_override=True,
        )
        assert result.safety_override is True
        assert result.colour == TrafficLightColour.RED
        assert result.blast_radius == BlastRadius.HIGH


class TestWorkflowState:
    def test_creation_minimal(self):
        state = WorkflowState(build_id="b-001", status=WorkflowStatus.PENDING)
        assert state.build_id == "b-001"
        assert state.status == WorkflowStatus.PENDING
        assert state.scenario is None
        assert state.failure_analysis is None
        assert state.code_fix is None
        assert state.traffic_light is None

    def test_defaults(self):
        state = WorkflowState(build_id="b-001", status=WorkflowStatus.PENDING)
        assert state.retry_count == 0
        assert state.max_retries == 3
        assert state.error_message == ""

    def test_created_at_is_set(self):
        before = datetime.now(timezone.utc)
        state = WorkflowState(build_id="b-001", status=WorkflowStatus.PENDING)
        after = datetime.now(timezone.utc)
        assert before <= state.created_at <= after
