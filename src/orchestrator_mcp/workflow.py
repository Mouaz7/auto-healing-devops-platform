"""Workflow engine for the Orchestrator.

Manages WorkflowState transitions through the 6-agent pipeline:
  PENDING → ANALYSING → GENERATING_FIX → VALIDATING
        → AWAITING_REVIEW | APPLYING_FIX | BLOCKED | COMPLETED | FAILED

Production concerns addressed here:
  - Periodic pruning of terminal states to prevent unbounded memory growth.
  - AWAITING_REVIEW timeout: workflows waiting for human approval for longer
    than REVIEW_TIMEOUT_HOURS are automatically advanced to BLOCKED.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.shared.models import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)

# Allowed state transitions — keys are current status, values are valid next states
VALID_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.PENDING:          {WorkflowStatus.ANALYSING, WorkflowStatus.FAILED},
    WorkflowStatus.ANALYSING:        {WorkflowStatus.GENERATING_FIX, WorkflowStatus.FAILED},
    WorkflowStatus.GENERATING_FIX:   {WorkflowStatus.VALIDATING, WorkflowStatus.FAILED, WorkflowStatus.BLOCKED},
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

# How long a YELLOW fix may wait for human review before auto-blocking
REVIEW_TIMEOUT_HOURS: int = 24

# Prune terminal workflows older than this to keep memory bounded
PRUNE_AFTER_HOURS: int = 48


class InvalidTransitionError(ValueError):
    """Raised when a requested state transition is not allowed."""


class WorkflowNotFoundError(KeyError):
    """Raised when a workflow ID is not registered."""


class WorkflowEngine:
    """In-memory registry and state machine for pipeline workflows.

    Memory management:
        Call prune_stale() periodically (e.g. from a background task) to
        remove terminal workflows older than PRUNE_AFTER_HOURS and to
        auto-block AWAITING_REVIEW workflows that have timed out.
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

        Only valid from non-terminal states that allow FAILED transitions.
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

    def stats(self) -> dict[str, int]:
        """Return a count of workflows grouped by status."""
        counts: dict[str, int] = {}
        for state in self._workflows.values():
            key = state.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def prune_stale(self) -> dict[str, int]:
        """Remove old terminal workflows and auto-block timed-out reviews.

        Returns:
            {"pruned": N, "timed_out": M} with counts of affected workflows.
        """
        now = datetime.now(timezone.utc)
        prune_cutoff = now - timedelta(hours=PRUNE_AFTER_HOURS)
        review_cutoff = now - timedelta(hours=REVIEW_TIMEOUT_HOURS)

        pruned = 0
        timed_out = 0
        to_delete: list[str] = []

        for build_id, state in self._workflows.items():
            # Auto-block stale AWAITING_REVIEW workflows
            if (
                state.status == WorkflowStatus.AWAITING_REVIEW
                and state.updated_at < review_cutoff
            ):
                state.status = WorkflowStatus.BLOCKED
                state.error_message = f"Review timeout after {REVIEW_TIMEOUT_HOURS}h"
                state.updated_at = now
                timed_out += 1
                logger.warning(
                    "workflow_review_timeout build_id=%s", build_id
                )

            # Remove terminal workflows beyond the prune window
            elif state.status in _TERMINAL_STATES and state.updated_at < prune_cutoff:
                to_delete.append(build_id)
                pruned += 1

        for build_id in to_delete:
            del self._workflows[build_id]

        if pruned or timed_out:
            logger.info(
                "workflow_prune_complete pruned=%d timed_out=%d total_remaining=%d",
                pruned, timed_out, len(self._workflows),
            )

        return {"pruned": pruned, "timed_out": timed_out}
