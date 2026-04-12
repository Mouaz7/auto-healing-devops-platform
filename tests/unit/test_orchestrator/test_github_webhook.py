"""Unit tests for orchestrator GitHub webhook handler."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.orchestrator_mcp.server import OrchestratorMCPServer
from src.orchestrator_mcp.workflow import WorkflowEngine
from src.shared.models import WorkflowState, WorkflowStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_server() -> OrchestratorMCPServer:
    server = OrchestratorMCPServer.__new__(OrchestratorMCPServer)
    server.engine = WorkflowEngine()
    return server


def _register(server: OrchestratorMCPServer, build_id: str, status: WorkflowStatus):
    state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
    server.engine.register(state)
    if status != WorkflowStatus.PENDING:
        # Walk the state machine to the desired status
        transitions = {
            WorkflowStatus.ANALYSING:       [WorkflowStatus.ANALYSING],
            WorkflowStatus.AWAITING_REVIEW: [
                WorkflowStatus.ANALYSING, WorkflowStatus.GENERATING_FIX,
                WorkflowStatus.VALIDATING, WorkflowStatus.AWAITING_REVIEW,
            ],
        }
        for step in transitions.get(status, []):
            server.engine.advance(build_id, step)


# ---------------------------------------------------------------------------
# _advance_after_approval
# ---------------------------------------------------------------------------

class TestAdvanceAfterApproval:
    def test_awaiting_review_advances_to_completed(self):
        server = _make_server()
        _register(server, "b1", WorkflowStatus.AWAITING_REVIEW)

        server._advance_after_approval("b1")  # pylint: disable=protected-access

        assert server.engine.get("b1").status == WorkflowStatus.COMPLETED

    def test_unknown_build_id_does_not_raise(self):
        server = _make_server()
        # Should log a warning but not crash
        server._advance_after_approval("nonexistent")  # pylint: disable=protected-access

    def test_already_completed_does_not_raise(self):
        server = _make_server()
        _register(server, "b2", WorkflowStatus.AWAITING_REVIEW)
        server._advance_after_approval("b2")  # pylint: disable=protected-access
        # Calling again should not raise
        server._advance_after_approval("b2")  # pylint: disable=protected-access
        assert server.engine.get("b2").status == WorkflowStatus.COMPLETED


# ---------------------------------------------------------------------------
# _verify_github_signature
# ---------------------------------------------------------------------------

class TestVerifyGithubSignature:
    def test_valid_signature_accepted(self):
        import hashlib
        import hmac

        secret = "my-secret"
        body = b'{"action": "closed"}'
        sig = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()

        class FakeRequest:
            headers = {"X-Hub-Signature-256": sig}

        with patch(
            "src.orchestrator_mcp.server._GITHUB_WEBHOOK_SECRET", secret
        ):
            result = OrchestratorMCPServer._verify_github_signature(body, FakeRequest())
        assert result is True

    def test_invalid_signature_rejected(self):
        class FakeRequest:
            headers = {"X-Hub-Signature-256": "sha256=deadbeef"}

        with patch(
            "src.orchestrator_mcp.server._GITHUB_WEBHOOK_SECRET", "secret"
        ):
            result = OrchestratorMCPServer._verify_github_signature(b"body", FakeRequest())
        assert result is False

    def test_missing_prefix_rejected(self):
        class FakeRequest:
            headers = {"X-Hub-Signature-256": "notsha256=abc"}

        result = OrchestratorMCPServer._verify_github_signature(b"body", FakeRequest())
        assert result is False
