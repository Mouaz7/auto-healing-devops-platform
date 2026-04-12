from __future__ import annotations

import pytest

from src.orchestrator_mcp.workflow import (
    WorkflowEngine,
    InvalidTransitionError,
    WorkflowNotFoundError,
    VALID_TRANSITIONS,
)
from src.shared.models import WorkflowState, WorkflowStatus


@pytest.fixture
def engine() -> WorkflowEngine:
    return WorkflowEngine()


@pytest.fixture
def pending_state() -> WorkflowState:
    return WorkflowState(build_id="build-1", status=WorkflowStatus.PENDING)


class TestWorkflowEngineRegister:
    def test_register_and_get(self, engine, pending_state):
        engine.register(pending_state)
        assert engine.get("build-1").build_id == "build-1"

    def test_duplicate_register_raises(self, engine, pending_state):
        engine.register(pending_state)
        duplicate = WorkflowState(build_id="build-1", status=WorkflowStatus.PENDING)
        with pytest.raises(ValueError, match="already registered"):
            engine.register(duplicate)

    def test_get_unknown_raises(self, engine):
        with pytest.raises(WorkflowNotFoundError):
            engine.get("nonexistent")


class TestWorkflowAdvance:
    def test_advance_pending_to_analysing(self, engine, pending_state):
        engine.register(pending_state)
        state = engine.advance("build-1", WorkflowStatus.ANALYSING)
        assert state.status == WorkflowStatus.ANALYSING

    def test_invalid_transition_raises(self, engine, pending_state):
        engine.register(pending_state)
        with pytest.raises(InvalidTransitionError):
            engine.advance("build-1", WorkflowStatus.COMPLETED)

    def test_advance_updates_timestamp(self, engine, pending_state):
        before = pending_state.updated_at
        engine.register(pending_state)
        state = engine.advance("build-1", WorkflowStatus.ANALYSING)
        assert state.updated_at >= before

    def test_advance_unknown_build_raises(self, engine):
        with pytest.raises(WorkflowNotFoundError):
            engine.advance("ghost", WorkflowStatus.ANALYSING)

    def test_full_happy_path(self, engine):
        state = WorkflowState(build_id="b-ok", status=WorkflowStatus.PENDING)
        engine.register(state)
        engine.advance("b-ok", WorkflowStatus.ANALYSING)
        engine.advance("b-ok", WorkflowStatus.GENERATING_FIX)
        engine.advance("b-ok", WorkflowStatus.VALIDATING)
        engine.advance("b-ok", WorkflowStatus.APPLYING_FIX)
        final = engine.advance("b-ok", WorkflowStatus.COMPLETED)
        assert final.status == WorkflowStatus.COMPLETED


class TestWorkflowFail:
    def test_fail_pending_workflow(self, engine, pending_state):
        engine.register(pending_state)
        state = engine.fail("build-1", reason="timeout")
        assert state.status == WorkflowStatus.FAILED
        assert state.error_message == "timeout"

    def test_fail_completed_raises(self, engine):
        s = WorkflowState(build_id="done", status=WorkflowStatus.COMPLETED)
        engine.register(s)
        with pytest.raises(InvalidTransitionError):
            engine.fail("done", reason="too late")

    def test_fail_unknown_build_raises(self, engine):
        with pytest.raises(WorkflowNotFoundError):
            engine.fail("ghost")


class TestListActive:
    def test_active_excludes_terminal(self, engine):
        engine.register(WorkflowState(build_id="b-pending",   status=WorkflowStatus.PENDING))
        engine.register(WorkflowState(build_id="b-completed", status=WorkflowStatus.COMPLETED))
        engine.register(WorkflowState(build_id="b-failed",    status=WorkflowStatus.FAILED))
        active = engine.list_active()
        ids = [s.build_id for s in active]
        assert "b-pending" in ids
        assert "b-completed" not in ids
        assert "b-failed" not in ids

    def test_empty_engine_returns_empty_list(self, engine):
        assert engine.list_active() == []


class TestValidTransitions:
    def test_terminal_states_have_no_transitions(self):
        for status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.BLOCKED]:
            assert VALID_TRANSITIONS[status] == set()

    def test_all_statuses_covered(self):
        for status in WorkflowStatus:
            assert status in VALID_TRANSITIONS
