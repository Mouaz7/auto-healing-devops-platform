"""Slack notifier — fixed Block Kit templates."""
# pylint: disable=duplicate-code,too-many-arguments,too-many-positional-arguments
from __future__ import annotations

import copy
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

_SLACK_TEMPLATES: dict[str, dict] = {
    "GREEN": {
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "✅ Auto-fix Applied"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "*Build:* __BUILD_ID__\n*Confidence:* __SCORE_PCT__%\n"
                              "*Files:* __FILES__\n__EXPLANATION__"}},
        ],
    },
    "YELLOW": {
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🟡 Human Review Required"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "*Build:* __BUILD_ID__\n*Confidence:* __SCORE_PCT__%\n"
                              "*Files:* __FILES__\n*Reason:* __REASON__\n__EXPLANATION__"}},
        ],
    },
    "RED": {
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🔴 Fix Blocked"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "*Build:* __BUILD_ID__\n*Files:* __FILES__\n*Reason:* __REASON__\n"
                              "Manual intervention required."}},
        ],
    },
}


def render_payload(colour: str, build_id: str, score: float,
                   reason: str, files: str = "", explanation: str = "") -> str:
    """Render a Slack Block Kit payload as a JSON string."""
    template = copy.deepcopy(_SLACK_TEMPLATES.get(colour, _SLACK_TEMPLATES["RED"]))
    raw = json.dumps(template)
    raw = raw.replace("__BUILD_ID__",    build_id)
    raw = raw.replace("__SCORE_PCT__",   str(round(score * 100)))
    raw = raw.replace("__REASON__",      reason)
    raw = raw.replace("__FILES__",       files)
    raw = raw.replace("__EXPLANATION__", explanation)
    return raw


async def send_slack_review_buttons(
    build_id: str,
    pr_url: str,
    pr_number: int,
    repo: str,
    score: float,
    explanation: str = "",
) -> bool:
    """Send YELLOW review message with Approve/Reject buttons to Slack."""
    if not _SLACK_WEBHOOK_URL:
        return False

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🟡 AI Fix — Human Review Required"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Build:* `{build_id}`\n"
                        f"*Confidence:* {round(score * 100)}%\n"
                        f"*PR:* <{pr_url}|View on GitHub>\n"
                        f"*Fix:* {explanation[:300]}"
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve & Merge"},
                        "style": "primary",
                        "action_id": "approve_fix",
                        "value": f"{repo}|{pr_number}|{build_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "style": "danger",
                        "action_id": "reject_fix",
                        "value": f"{repo}|{pr_number}|{build_id}",
                    },
                ],
            },
        ]
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _SLACK_WEBHOOK_URL,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        ok = resp.status_code == 200
        logger.info("slack_review_buttons build_id=%s ok=%s", build_id, ok)
        return ok


async def send_slack_notification(
    colour: str, build_id: str, score: float, reason: str,
    files: str = "", explanation: str = "",
) -> bool:
    """POST a Block Kit message to the Slack webhook. Returns True on success."""
    if not _SLACK_WEBHOOK_URL:
        logger.debug("slack_notify skipped — SLACK_WEBHOOK_URL not set")
        return False
    payload = render_payload(colour, build_id, score, reason, files, explanation)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _SLACK_WEBHOOK_URL, content=payload,
            headers={"Content-Type": "application/json"},
        )
        ok = resp.status_code == 200
        logger.info("slack_notify build_id=%s colour=%s ok=%s", build_id, colour, ok)
        return ok


async def send_slack_pipeline_started(build_id: str, repo: str = "") -> bool:
    """Send an immediate "started" Slack notice so the user sees that auto-heal
    is working. The final GREEN/YELLOW/RED message follows when the pipeline
    completes (can take 5-20 min for hard cases — without this, the user has
    no visibility during the wait).
    """
    if not _SLACK_WEBHOOK_URL:
        return False
    repo_line = f"*Repo:* `{repo}`\n" if repo else ""
    payload = json.dumps({
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "⚙️ Auto-heal Started"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": (f"*Build:* `{build_id}`\n{repo_line}"
                               "Pipeline running — analysing logs and "
                               "generating fix. Result follows in a few minutes.")}},
        ],
    })
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                _SLACK_WEBHOOK_URL, content=payload,
                headers={"Content-Type": "application/json"},
            )
        ok = resp.status_code == 200
        logger.info("slack_pipeline_started build_id=%s ok=%s", build_id, ok)
        return ok
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("slack_pipeline_started_failed build_id=%s err=%s",
                       build_id, exc)
        return False
