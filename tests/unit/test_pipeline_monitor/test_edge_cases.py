"""Edge case tests for Pipeline Monitor (Agent 1) webhook handler."""
from __future__ import annotations

import pytest

from src.jenkins_mcp.webhook_handler import WebhookHandler


@pytest.fixture
def handler() -> WebhookHandler:
    return WebhookHandler()


class TestDuplicateHandling:
    def test_duplicate_build_id_returns_none(self, handler):
        """Same build_id twice → second call returns None."""
        payload = {"build_id": "build-dup", "status": "FAILED", "job_name": "j"}
        first = handler.handle(payload)
        second = handler.handle(payload)
        assert first is not None
        assert second is None

    def test_set_persists_across_calls(self, handler):
        """seen_builds set is not reset between calls."""
        p1 = {"build_id": "b1", "status": "FAILED"}
        p2 = {"build_id": "b2", "status": "FAILED"}
        handler.handle(p1)
        handler.handle(p2)
        # Both are now seen — duplicates return None
        assert handler.handle(p1) is None
        assert handler.handle(p2) is None

    def test_different_build_ids_both_accepted(self, handler):
        """Two different build_ids are both accepted."""
        p1 = {"build_id": "b-001", "status": "FAILED"}
        p2 = {"build_id": "b-002", "status": "FAILED"}
        assert handler.handle(p1) is not None
        assert handler.handle(p2) is not None


class TestMissingAndEmptyPayload:
    def test_empty_payload_returns_none(self, handler):
        """Empty dict → None."""
        assert handler.handle({}) is None

    def test_missing_build_id_returns_none(self, handler):
        """Payload without build_id → None."""
        assert handler.handle({"status": "FAILED"}) is None

    def test_empty_string_build_id_returns_none(self, handler):
        """build_id='' → None."""
        assert handler.handle({"build_id": "", "status": "FAILED"}) is None

    def test_whitespace_only_build_id_returns_none(self, handler):
        """build_id='   ' → None (stripped to empty)."""
        assert handler.handle({"build_id": "   ", "status": "FAILED"}) is None


class TestStatusFiltering:
    def test_success_status_ignored(self, handler):
        """SUCCESS build → None."""
        assert handler.handle({"build_id": "b1", "status": "SUCCESS"}) is None

    def test_failed_status_accepted(self, handler):
        """FAILED → accepted."""
        result = handler.handle({"build_id": "b-f1", "status": "FAILED"})
        assert result is not None

    def test_failure_status_accepted(self, handler):
        """FAILURE (Jenkins variant) → accepted."""
        result = handler.handle({"build_id": "b-f2", "status": "FAILURE"})
        assert result is not None

    def test_aborted_status_accepted(self, handler):
        """ABORTED → accepted."""
        result = handler.handle({"build_id": "b-f3", "status": "ABORTED"})
        assert result is not None

    def test_error_status_accepted(self, handler):
        """ERROR → accepted."""
        result = handler.handle({"build_id": "b-f4", "status": "ERROR"})
        assert result is not None

    def test_unknown_status_ignored(self, handler):
        """Unknown status → None."""
        assert handler.handle({"build_id": "b1", "status": "PENDING"}) is None


class TestReset:
    def test_reset_clears_seen_builds(self, handler):
        """After reset(), previously seen builds are accepted again."""
        p = {"build_id": "reset-b1", "status": "FAILED"}
        handler.handle(p)
        assert handler.handle(p) is None
        handler.reset()
        assert handler.handle(p) is not None
