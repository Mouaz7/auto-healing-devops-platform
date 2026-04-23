"""Slack slash-command handler for /autoheal.

Supported commands:
  /autoheal status <build_id>   — show current workflow status
  /autoheal list                — list last 10 active workflows
  /autoheal stats               — show success rates by error type

The handler validates Slack's HMAC-SHA256 request signature before processing.
It returns an immediate 200 with JSON so Slack doesn't show "operation timeout".

Mount at:  POST /webhooks/slack/commands

Env vars:
  SLACK_SIGNING_SECRET  — required for signature verification
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
_REPLAY_WINDOW_SECONDS = 300  # 5 minutes — Slack's standard replay-attack window


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(request_body: bytes,
                       timestamp: str,
                       signature: str) -> bool:
    """Verify Slack's request signature (HMAC-SHA256).

    Returns False if the secret is not configured (misconfiguration guard).
    """
    if not _SIGNING_SECRET:
        logger.error("slack_signing_secret_not_configured")
        return False

    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    if abs(time.time() - ts) > _REPLAY_WINDOW_SECONDS:
        logger.warning("slack_signature_replay_attack ts=%s", timestamp)
        return False

    base = f"v0:{timestamp}:{request_body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(
        _SIGNING_SECRET.encode(),
        base.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Response formatters
# ---------------------------------------------------------------------------

def _status_response(build_id: str, workflow: dict[str, Any] | None) -> dict:
    if workflow is None:
        return {
            "response_type": "ephemeral",
            "text": f":x: Build `{build_id}` not found.",
        }

    status  = workflow.get("status", "UNKNOWN")
    colour  = workflow.get("colour", "—")
    score   = workflow.get("final_score")
    score_s = f"{score:.0%}" if score is not None else "—"

    emoji = {"GREEN": ":large_green_circle:", "YELLOW": ":large_yellow_circle:",
             "RED": ":red_circle:"}.get(colour, ":white_circle:")

    return {
        "response_type": "ephemeral",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *Build `{build_id}`*\n"
                        f"Status: *{status}* | Colour: *{colour}* | Score: *{score_s}*"
                    ),
                },
            }
        ],
    }


def _list_response(workflows: list[dict]) -> dict:
    if not workflows:
        return {"response_type": "ephemeral", "text": "No active workflows found."}

    lines = []
    for wf in workflows[:10]:
        bid    = wf.get("build_id", "?")
        status = wf.get("status", "?")
        colour = wf.get("colour", "")
        emoji  = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(colour, "⚪")
        lines.append(f"{emoji} `{bid}` — {status}")

    return {
        "response_type": "ephemeral",
        "text": "*Recent workflows:*\n" + "\n".join(lines),
    }


def _stats_response(stats: dict) -> dict:
    if not stats:
        return {"response_type": "ephemeral", "text": "No fix history yet."}

    lines = ["*Fix success rates by error type:*"]
    for et, s in stats.items():
        total  = s.get("total", 0)
        green  = int(s.get("green_rate", 0) * 100)
        yellow = int(s.get("yellow_rate", 0) * 100)
        red    = int(s.get("red_rate", 0) * 100)
        lines.append(f"• `{et}` — {total} fixes | 🟢 {green}% 🟡 {yellow}% 🔴 {red}%")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def handle_slash_command(request: web.Request) -> web.Response:
    """Handle POST /webhooks/slack/commands.

    Validates signature, parses command, returns immediate response.
    """
    body = await request.read()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_signature(body, timestamp, signature):
        logger.warning("slack_slash_invalid_signature")
        return web.json_response({"error": "invalid_signature"}, status=403)

    # Slack sends application/x-www-form-urlencoded
    try:
        form = await request.post()
    except Exception:
        form = {}  # type: ignore[assignment]

    command  = form.get("command", "")
    text     = (form.get("text") or "").strip()
    parts    = text.split()
    sub_cmd  = parts[0].lower() if parts else "help"
    arg      = parts[1] if len(parts) > 1 else ""

    logger.info("slack_slash command=%s sub=%s arg=%s", command, sub_cmd, arg)

    if sub_cmd == "status":
        if not arg:
            return web.json_response({
                "response_type": "ephemeral",
                "text": "Usage: `/autoheal status <build_id>`",
            })
        from src.orchestrator_mcp.workflow import WorkflowRegistry
        wf = WorkflowRegistry._instance.get(arg) if WorkflowRegistry._instance else None
        return web.json_response(_status_response(arg, wf))

    if sub_cmd == "list":
        from src.orchestrator_mcp.workflow import WorkflowRegistry
        reg = WorkflowRegistry._instance
        if reg:
            all_wf = [reg.get(bid) for bid in list(reg._workflows)[-10:]]
            workflows = [w for w in all_wf if w]
        else:
            workflows = []
        return web.json_response(_list_response(workflows))

    if sub_cmd == "stats":
        from src.shared.fix_memory import fix_memory
        stats = fix_memory.stats()
        return web.json_response(_stats_response(stats))

    # Default: help
    return web.json_response({
        "response_type": "ephemeral",
        "text": (
            "*Auto-Healer slash commands:*\n"
            "• `/autoheal status <build_id>` — check a specific build\n"
            "• `/autoheal list` — list recent workflows\n"
            "• `/autoheal stats` — show AI fix success rates"
        ),
    })
