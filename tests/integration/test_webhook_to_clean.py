"""Integration test: webhook acceptance → log cleaning pipeline."""
from __future__ import annotations

import pytest

from src.jenkins_mcp.webhook_handler import WebhookHandler
from src.log_cleaner_mcp.pipeline import LogCleaningPipeline


@pytest.fixture
def handler() -> WebhookHandler:
    return WebhookHandler()


@pytest.fixture
def pipeline() -> LogCleaningPipeline:
    return LogCleaningPipeline(nim_client=None)


@pytest.fixture
def raw_build_log() -> str:
    return (
        "\x1b[31m[ERROR]\x1b[0m Build failed\n"
        "2024-01-15T10:00:00Z DEBUG initialising\n"
        "2024-01-15T10:00:01Z DEBUG connecting\n"
        "\n"
        "2024-01-15T10:00:02Z ERROR ImportError: cannot import name Foo\n"
        "Traceback (most recent call last):\n"
        '  File "app.py", line 1, in <module>\n'
        "    from lib import Foo\n"
        "ImportError: cannot import name Foo\n"
    )


class TestWebhookToClean:
    def test_accepted_event_can_be_cleaned(self, handler, pipeline, raw_build_log):
        payload = {
            "build_id": "jenkins-99",
            "repo": "example/app",
            "branch": "main",
            "status": "FAILURE",
            "job_name": "example-app-ci",
            "log_url": "http://jenkins.local/job/99/consoleText",
        }
        event = handler.handle(payload)
        assert event is not None

        result = pipeline.clean(raw_build_log)
        assert result.cleaned_lines < result.original_lines
        assert "ImportError" in result.cleaned_text

    def test_ignored_event_does_not_proceed(self, handler, pipeline, raw_build_log):
        payload = {"build_id": "jenkins-100", "status": "SUCCESS"}
        event = handler.handle(payload)
        assert event is None

    def test_duplicate_event_not_cleaned_twice(self, handler, pipeline, raw_build_log):
        payload = {
            "build_id": "jenkins-101",
            "status": "FAILURE",
        }
        e1 = handler.handle(payload)
        e2 = handler.handle(payload)
        assert e1 is not None
        assert e2 is None  # duplicate filtered out

    def test_pipeline_reduces_noisy_log(self, pipeline, raw_build_log):
        result = pipeline.clean(raw_build_log)
        assert result.reduction_ratio > 0
        assert result.used_llm is False

    def test_ansi_removed_from_cleaned_log(self, pipeline, raw_build_log):
        result = pipeline.clean(raw_build_log)
        assert "\x1b" not in result.cleaned_text
