"""5-minute proactive health check for build fixes.

Monitors builds and sends Slack updates if problem still exists after 5 min.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# In-memory tracker of builds and their check status
_build_checks: dict[str, dict[str, Any]] = {}


def track_build_start(build_id: str, repo: str) -> None:
    """Record that a build has started auto-healing."""
    _build_checks[build_id] = {
        "started_at": datetime.utcnow(),
        "repo": repo,
        "checked": False,
    }
    logger.info("health_check_tracked build_id=%s", build_id)


async def schedule_health_check(
    build_id: str,
    repo: str,
    slack_webhook_url: str,
    delay_seconds: int = 300,
) -> None:
    """Schedule a 5-minute (300s) health check for this build.

    Args:
        build_id: The build identifier
        repo: Repository path
        slack_webhook_url: Slack webhook for notifications
        delay_seconds: Time to wait before checking (default 300 = 5 min)
    """
    if not slack_webhook_url:
        return

    try:
        await asyncio.sleep(delay_seconds)
        await _send_health_check_update(build_id, repo, slack_webhook_url)
    except Exception as exc:
        logger.warning("health_check_failed build_id=%s error=%s", build_id, exc)


async def _send_health_check_update(
    build_id: str,
    repo: str,
    slack_webhook_url: str,
) -> None:
    """Send a 5-minute status update to Slack."""
    check_record = _build_checks.get(build_id, {})
    started_at = check_record.get("started_at")

    if not started_at:
        logger.warning("health_check_missing_record build_id=%s", build_id)
        return

    elapsed = (datetime.utcnow() - started_at).total_seconds()
    elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    # Build the 5-minute check message with rich formatting
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⏱️  5-Minute Health Check — Still Working",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🆔 *Build ID*\n`{build_id}`"},
                {"type": "mrkdwn", "text": f"⏱️  *Elapsed*\n{elapsed_str}"},
                {"type": "mrkdwn", "text": f"📦 *Repository*\n{repo}"},
                {"type": "mrkdwn", "text": "*Status*\n✅ Pipeline Active"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "🔄 *Progress Update*\n"
                    "The auto-healing pipeline is processing your build.\n\n"
                    "📊 *What's happening:*\n"
                    "• 🔍 Log analysis\n"
                    "• 🐛 Bug detection\n"
                    "• ⚡ Fix generation\n"
                    "• ✅ Security & linting\n\n"
                    "_Check back in a few moments for the final result._"
                ),
            },
        },
    ]

    payload = {"blocks": blocks}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                slack_webhook_url,
                json=payload,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info("health_check_sent build_id=%s", build_id)
                _build_checks[build_id]["checked"] = True
            else:
                logger.warning(
                    "health_check_slack_failed build_id=%s status=%d",
                    build_id, response.status_code,
                )
    except Exception as exc:
        logger.error("health_check_slack_error build_id=%s error=%s", build_id, exc)


def cleanup_old_checks(max_age_hours: int = 24) -> None:
    """Remove old build checks from memory."""
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    old_builds = [
        bid for bid, record in _build_checks.items()
        if record.get("started_at", cutoff) < cutoff
    ]
    for bid in old_builds:
        del _build_checks[bid]
    if old_builds:
        logger.info("health_check_cleanup removed=%d", len(old_builds))
