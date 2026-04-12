from __future__ import annotations

import pytest

from src.jenkins_mcp.webhook_handler import WebhookHandler
from src.shared.models import BuildEvent


@pytest.fixture
def handler() -> WebhookHandler:
    return WebhookHandler()


@pytest.fixture
def valid_payload() -> dict:
    return {
        "build_id": "jenkins-42",
        "repo": "example/app",
        "branch": "main",
        "status": "FAILURE",
        "job_name": "example-app-ci",
        "log_url": "http://jenkins.local/job/42/consoleText",
    }


class TestValidPayload:
    def test_returns_build_event(self, handler, valid_payload):
        event = handler.handle(valid_payload)
        assert isinstance(event, BuildEvent)

    def test_build_id_mapped(self, handler, valid_payload):
        event = handler.handle(valid_payload)
        assert event.build_id == "jenkins-42"

    def test_repo_branch_mapped(self, handler, valid_payload):
        event = handler.handle(valid_payload)
        assert event.repo == "example/app"
        assert event.branch == "main"

    def test_status_uppercased(self, handler, valid_payload):
        valid_payload["status"] = "failure"
        event = handler.handle(valid_payload)
        assert event.status == "FAILURE"

    def test_timestamp_is_set(self, handler, valid_payload):
        event = handler.handle(valid_payload)
        assert event.timestamp is not None

    def test_timestamp_is_timezone_aware(self, handler, valid_payload):
        event = handler.handle(valid_payload)
        assert event.timestamp.tzinfo is not None

    def test_failed_status_accepted(self, handler, valid_payload):
        valid_payload["status"] = "FAILED"
        assert handler.handle(valid_payload) is not None

    def test_error_status_accepted(self, handler, valid_payload):
        valid_payload["status"] = "ERROR"
        assert handler.handle(valid_payload) is not None

    def test_aborted_status_accepted(self, handler, valid_payload):
        valid_payload["status"] = "ABORTED"
        assert handler.handle(valid_payload) is not None


class TestDuplicateFiltering:
    def test_duplicate_returns_none(self, handler, valid_payload):
        handler.handle(valid_payload)
        assert handler.handle(valid_payload) is None

    def test_different_build_ids_both_accepted(self, handler, valid_payload):
        e1 = handler.handle(valid_payload)
        valid_payload["build_id"] = "jenkins-43"
        e2 = handler.handle(valid_payload)
        assert e1 is not None
        assert e2 is not None
        assert e1.build_id != e2.build_id

    def test_reset_clears_dedup_state(self, handler, valid_payload):
        handler.handle(valid_payload)
        handler.reset()
        event = handler.handle(valid_payload)
        assert event is not None


class TestInvalidPayload:
    def test_missing_build_id_returns_none(self, handler, valid_payload):
        del valid_payload["build_id"]
        assert handler.handle(valid_payload) is None

    def test_empty_build_id_returns_none(self, handler, valid_payload):
        valid_payload["build_id"] = ""
        assert handler.handle(valid_payload) is None

    def test_whitespace_build_id_returns_none(self, handler, valid_payload):
        valid_payload["build_id"] = "   "
        assert handler.handle(valid_payload) is None

    def test_success_status_ignored(self, handler, valid_payload):
        valid_payload["status"] = "SUCCESS"
        assert handler.handle(valid_payload) is None

    def test_unknown_status_ignored(self, handler, valid_payload):
        valid_payload["status"] = "UNSTABLE"
        assert handler.handle(valid_payload) is None

    def test_empty_payload_returns_none(self, handler):
        assert handler.handle({}) is None

    def test_missing_optional_fields_default_empty(self, handler):
        event = handler.handle({"build_id": "b-1", "status": "FAILURE"})
        assert event is not None
        assert event.repo == ""
        assert event.branch == ""
        assert event.job_name == ""
        assert event.log_url == ""
