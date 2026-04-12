"""Workflow engine for the Orchestrator (Agent skeleton — Sprint 2).

Manages WorkflowState transitions through the 6-agent pipeline.
Full agent integration is deferred to Sprint 3; this skeleton provides:
  - State-machine validation (VALID_TRANSITIONS)
  - In-memory workflow registry
  - advance() / fail() / get() operations
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.shared.models import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)

# Allowed state transitions — keys are current status, values are valid next states
VALID_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.PENDING:          {WorkflowStatus.ANALYSING, WorkflowStatus.FAILED},
    WorkflowStatus.ANALYSING:        {WorkflowStatus.GENERATING_FIX, WorkflowStatus.FAILED},
    WorkflowStatus.GENERATING_FIX:   {WorkflowStatus.VALIDATING, WorkflowStatus.FAILED},
    WorkflowStatus.VALIDATING:       {
        WorkflowStatus.AWAITING_REVIEW,
        WorkflowStatus.APPLYING_FIX,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.FAILED,
    },
    WorkflowStatus.AWAITING_REVIEW:  {WorkflowStatus.APPLYING_FIX, WorkflowStatus.BLOCKED},
    WorkflowStatus.APPLYING_FIX:     {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED},
    WorkflowStatus.COMPLETED:        set(),   # terminal
    WorkflowStatus.FAILED:           set(),   # terminal
    WorkflowStatus.BLOCKED:          set(),   # terminal
}

_TERMINAL_STATES: frozenset[WorkflowStatus] = frozenset({
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
})


class InvalidTransitionError(ValueError):
    """Raised when a requested state transition is not allowed."""


class WorkflowNotFoundError(KeyError):
    """Raised when a workflow ID is not registered."""


class WorkflowEngine:
    """In-memory registry and state machine for pipeline workflows.

    Sprint 2 skeleton: no real agent calls; transition logic only.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, state: WorkflowState) -> None:
        """Register a new workflow. Raises ValueError if already registered."""
        if state.build_id in self._workflows:
            raise ValueError(f"Workflow '{state.build_id}' already registered")
        self._workflows[state.build_id] = state
        logger.info("workflow_registered build_id=%s status=%s",
                    state.build_id, state.status.value)

    def get(self, build_id: str) -> WorkflowState:
        """Return the current state for *build_id*.

        Raises:
            WorkflowNotFoundError: If the build has not been registered.
        """
        if build_id not in self._workflows:
            raise WorkflowNotFoundError(build_id)
        return self._workflows[build_id]

    def advance(self, build_id: str, next_status: WorkflowStatus) -> WorkflowState:
        """Transition *build_id* to *next_status*.

        Raises:
            WorkflowNotFoundError: Build not found.
            InvalidTransitionError: Transition not allowed by state machine.
        """
        state = self.get(build_id)
        allowed = VALID_TRANSITIONS.get(state.status, set())
        if next_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition '{build_id}' from {state.status.value} "
                f"to {next_status.value}"
            )
        state.status = next_status
        state.updated_at = datetime.now(timezone.utc)
        logger.info("workflow_advanced build_id=%s status=%s",
                    build_id, next_status.value)
        return state

    def fail(self, build_id: str, reason: str = "") -> WorkflowState:
        """Mark *build_id* as FAILED with an optional *reason*.

        Only transitions that allow FAILED in VALID_TRANSITIONS will succeed.
        """
        state = self.get(build_id)
        allowed = VALID_TRANSITIONS.get(state.status, set())
        if WorkflowStatus.FAILED not in allowed:
            raise InvalidTransitionError(
                f"Cannot fail '{build_id}' from terminal state {state.status.value}"
            )
        state.status = WorkflowStatus.FAILED
        state.error_message = reason
        state.updated_at = datetime.now(timezone.utc)
        logger.warning("workflow_failed build_id=%s reason=%s", build_id, reason)
        return state

    def list_active(self) -> list[WorkflowState]:
        """Return all non-terminal workflows."""
        return [s for s in self._workflows.values() if s.status not in _TERMINAL_STATES]

    def all_build_ids(self) -> list[str]:
        """Return all registered build IDs."""
        return list(self._workflows.keys())
