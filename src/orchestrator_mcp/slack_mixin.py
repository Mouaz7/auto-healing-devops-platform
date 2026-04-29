"""SlackMixin — interactive button handling for PR Approve / Reject."""
from __future__ import annotations

import json
import logging
import os
import urllib.parse

import httpx
from aiohttp import web

from src.shared.adaptive_thresholds import adaptive_thresholds
from src.shared.audit_log import audit
from src.shared.fix_memory import fix_memory

logger = logging.getLogger(__name__)


def _approved_block(build_id: str, pr_url: str, pr_number: int, user_id: str) -> dict:
    return {
        "replace_original": True,
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "✅ Fix Approved & Merged"}},
            {"type": "section",
             "text": {"type": "mrkdwn", "text": (
                f"*Build:* `{build_id}`\n"
                f"*PR:* <{pr_url}|#{pr_number}> — merged successfully\n"
                f"*Approved by:* <@{user_id}>\n"
                f"*Status:* Fix applied to `main` branch ✅"
             )}},
        ],
    }


def _merge_failed_block(build_id: str, pr_url: str, pr_number: int, status: int) -> dict:
    return {
        "replace_original": True,
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "⚠️ Merge Failed"}},
            {"type": "section",
             "text": {"type": "mrkdwn", "text": (
                f"*Build:* `{build_id}`\n"
                f"*PR:* <{pr_url}|#{pr_number}>\n"
                f"*Error:* Could not merge (status {status})\n"
                f"Please merge manually on GitHub."
             )}},
        ],
    }


def _rejected_block(build_id: str, pr_url: str, pr_number: int, user_id: str) -> dict:
    return {
        "replace_original": True,
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "❌ Fix Rejected"}},
            {"type": "section",
             "text": {"type": "mrkdwn", "text": (
                f"*Build:* `{build_id}`\n"
                f"*PR:* <{pr_url}|#{pr_number}> — closed\n"
                f"*Rejected by:* <@{user_id}>\n"
                f"*Next step:* Manual fix required 🔧"
             )}},
        ],
    }


def _record_adaptive_decision(build_id: str, approved: bool) -> None:
    """Feed a human decision back to the adaptive threshold learner."""
    try:
        records = fix_memory._load_records()  # pylint: disable=protected-access
        for rec in reversed(records):
            if rec.get("build_id") == build_id and not rec.get("_update"):
                error_type = rec.get("error_type", "")
                confidence = rec.get("confidence", 0.0)
                if error_type:
                    adaptive_thresholds.record_decision(error_type, confidence, approved)
                break
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("adaptive_threshold_update_failed build_id=%s error=%s",
                       build_id, exc)


class SlackMixin:
    """Slack interactive webhook handler."""

    async def slack_webhook(self, request: web.Request) -> web.Response:
        """Handle Slack interactive button clicks (Approve / Reject)."""
        body = await request.text()
        payload_str = urllib.parse.unquote(body.replace("payload=", "", 1))
        try:
            payload = json.loads(payload_str)
        except Exception:  # pylint: disable=broad-exception-caught
            return web.Response(text="invalid payload", status=400)

        actions = payload.get("actions", [])
        response_url = payload.get("response_url", "")
        if not actions:
            return web.Response(text="ok")

        action = actions[0]
        action_id = action.get("action_id", "")
        value = action.get("value", "")

        try:
            repo, pr_number_str, build_id = value.split("|")
            pr_number = int(pr_number_str)
        except ValueError:
            return web.Response(text="invalid value", status=400)

        user_id = payload.get("user", {}).get("id", "unknown")
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Authorization": f"token {token}",
                   "Accept": "application/vnd.github+json"}

        async with httpx.AsyncClient(timeout=15) as client:
            if action_id == "approve_fix":
                resp = await client.put(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
                    headers=headers, json={"merge_method": "squash"},
                )
                if resp.status_code == 200:
                    fix_memory.update_outcome(build_id, approved=True)
                    _record_adaptive_decision(build_id, approved=True)
                    audit.log("pr_approved", build_id=build_id, pr_number=pr_number,
                              repo=repo, approved_by=user_id)
                    logger.info("slack_approved build_id=%s pr=%d", build_id, pr_number)
                    updated_msg = _approved_block(build_id, pr_url, pr_number, user_id)
                else:
                    updated_msg = _merge_failed_block(
                        build_id, pr_url, pr_number, resp.status_code,
                    )

            elif action_id == "reject_fix":
                await client.patch(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                    headers=headers, json={"state": "closed"},
                )
                fix_memory.update_outcome(build_id, approved=False)
                _record_adaptive_decision(build_id, approved=False)
                audit.log("pr_rejected", build_id=build_id, pr_number=pr_number,
                          repo=repo, rejected_by=user_id)
                logger.info("slack_rejected build_id=%s pr=%d", build_id, pr_number)
                updated_msg = _rejected_block(build_id, pr_url, pr_number, user_id)
            else:
                return web.Response(text="ok")

            if response_url:
                await client.post(
                    response_url, json=updated_msg,
                    headers={"Content-Type": "application/json"},
                )

        return web.Response(text="", status=200)
