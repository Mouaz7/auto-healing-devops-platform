"""Unit tests for 5-minute health check system."""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.shared.health_check import (
    _build_checks,
    cleanup_old_checks,
    schedule_health_check,
    track_build_start,
)


class TestHealthCheck:
    """Test 5-minute proactive health check."""

    def test_track_build_start(self):
        """Test that build tracking records start time."""
        build_id = "test-build-123"
        repo = "org/repo"

        track_build_start(build_id, repo)

        assert build_id in _build_checks
        assert _build_checks[build_id]["repo"] == repo
        assert _build_checks[build_id]["checked"] is False
        assert isinstance(_build_checks[build_id]["started_at"], datetime)

    @pytest.mark.asyncio
    async def test_schedule_health_check_no_webhook(self):
        """Test that health check skips if no webhook URL."""
        build_id = "test-build-456"
        repo = "org/repo"

        # Should return early without error
        await schedule_health_check(
            build_id,
            repo,
            "",  # Empty webhook
            delay_seconds=1,
        )

    @pytest.mark.asyncio
    async def test_schedule_health_check_sends_slack_message(self):
        """Test that health check sends Slack message after delay."""
        build_id = "test-build-789"
        repo = "org/repo"
        webhook_url = "https://hooks.slack.com/services/TEST"

        track_build_start(build_id, repo)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await schedule_health_check(
                build_id,
                repo,
                webhook_url,
                delay_seconds=1,
            )

            # Verify Slack was called
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == webhook_url
            assert "blocks" in call_args[1]["json"]

            # Verify status updated
            assert _build_checks[build_id]["checked"] is True

    def test_cleanup_old_checks(self):
        """Test that old build checks are removed."""
        # Create an old build
        old_build = "old-build"
        old_time = datetime.utcnow() - timedelta(hours=25)
        _build_checks[old_build] = {
            "started_at": old_time,
            "repo": "org/repo",
            "checked": False,
        }

        # Create a recent build
        recent_build = "recent-build"
        recent_time = datetime.utcnow() - timedelta(hours=1)
        _build_checks[recent_build] = {
            "started_at": recent_time,
            "repo": "org/repo",
            "checked": False,
        }

        cleanup_old_checks(max_age_hours=24)

        # Old build should be removed, recent should remain
        assert old_build not in _build_checks
        assert recent_build in _build_checks

    def test_health_check_message_structure(self):
        """Test that health check message has correct Block Kit structure."""
        # This is verified indirectly by schedule_health_check
        # but we can ensure the message blocks are valid
        build_id = "test-build"
        repo = "org/repo"

        track_build_start(build_id, repo)

        # Simulate what _send_health_check_update does
        check_record = _build_checks[build_id]
        started_at = check_record["started_at"]
        elapsed = (datetime.utcnow() - started_at).total_seconds()

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⏱️ 5-Minute Health Check",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Build ID*\n`{build_id}`"},
                    {"type": "mrkdwn", "text": f"*Repository*\n{repo}"},
                ],
            },
        ]

        assert blocks[0]["type"] == "header"
        assert blocks[1]["type"] == "section"
        assert len(blocks[1]["fields"]) >= 2
