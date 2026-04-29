"""Slack slash-command handler for /autoheal.

Supported commands:
  /autoheal status   <build_id>   — current workflow status + score
  /autoheal list                  — last 10 workflows with colour
  /autoheal stats                 — fix success rates by error type
  /autoheal retry    <build_id>   — re-submit a failed build to the pipeline
  /autoheal explain  <build_id>   — plain-English AI explanation of the fix
  /autoheal rollback <build_id>   — close the open PR (undo the fix)
  /autoheal history  <file_path>  — fix history for a specific source file
  /autoheal top                   — most problematic files this session
  /autoheal thresholds            — show adaptive confidence thresholds

All requests are verified with Slack's HMAC-SHA256 signature.
Responses are immediate (< 3 s) to avoid Slack timeout errors.

Env vars:
  SLACK_SIGNING_SECRET   — required for signature verification
  GITHUB_TOKEN           — required for rollback (PR close)
  ORCHESTRATOR_URL       — internal URL for retry (default: http://localhost:8085)

Response builders live in slash_responses.py.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections import Counter

import httpx
from aiohttp import web

from src.notification_mcp.slash_responses import (
    explain_response,
    help_response,
    history_response,
    list_response,
    stats_response,
    status_response,
    thresholds_response,
    top_response,
    usage,
)

logger = logging.getLogger(__name__)

_SIGNING_SECRET   = os.getenv("SLACK_SIGNING_SECRET", "")
_GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN", "")
_ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8085")
_REPLAY_WINDOW    = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Validate Slack's HMAC-SHA256 request signature."""
    if not _SIGNING_SECRET:
        logger.error("slack_signing_secret_not_configured")
        return False
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > _REPLAY_WINDOW:
        logger.warning("slack_signature_replay_attack ts=%s", timestamp)
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(
        _SIGNING_SECRET.encode(), base.encode(), hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_engine():
    """Return the global WorkflowEngine instance if available."""
    try:
        from src.orchestrator_mcp import server as _srv_mod
        return getattr(_srv_mod, "_engine_instance", None)
    except Exception:  # pylint: disable=broad-exception-caught
        return None


# ---------------------------------------------------------------------------
# Sub-command implementations — each returns the dict for json_response
# ---------------------------------------------------------------------------

def _cmd_status(arg: str) -> dict:
    if not arg:
        return usage("Usage: `/autoheal status <build_id>`")
    engine = _get_engine()
    try:
        state = engine.get(arg) if engine else None
    except Exception:  # pylint: disable=broad-exception-caught
        state = None
    return status_response(arg, state)


def _cmd_list() -> dict:
    engine = _get_engine()
    return list_response(engine.list_active() if engine else [])


def _cmd_stats() -> dict:
    from src.shared.fix_memory import fix_memory
    return stats_response(fix_memory.stats())


async def _cmd_retry(arg: str) -> dict:
    if not arg:
        return usage("Usage: `/autoheal retry <build_id>`")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{_ORCHESTRATOR_URL}/tools/retry_build",
                json={"build_id": arg},
            )
        if resp.status_code in (200, 202):
            return usage(f"♻️ Build `{arg}` has been re-submitted to the pipeline.")
        return usage(f"⚠️ Could not retry build `{arg}` (status {resp.status_code}).")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return usage(f"⚠️ Retry failed: {exc}")


def _cmd_explain(arg: str) -> dict:
    if not arg:
        return usage("Usage: `/autoheal explain <build_id>`")
    from src.shared.fix_memory import fix_memory
    matching = [
        r for r in fix_memory._load_records()  # pylint: disable=protected-access
        if r.get("build_id") == arg and not r.get("_update")
    ]
    return explain_response(arg, matching)


def _cmd_history(arg: str) -> dict:
    if not arg:
        return usage("Usage: `/autoheal history <file_path>`")
    from src.shared.fix_memory import fix_memory
    all_recs = fix_memory._load_records()  # pylint: disable=protected-access
    matching = [
        r for r in reversed(all_recs)
        if not r.get("_update") and arg in (r.get("files_key") or "")
    ]
    return history_response(arg, matching)


def _cmd_top() -> dict:
    from src.shared.fix_memory import fix_memory
    counter: Counter = Counter()
    for rec in fix_memory._load_records():  # pylint: disable=protected-access
        if rec.get("_update"):
            continue
        for f in (rec.get("files_key") or "").split(","):
            if f.strip():
                counter[f.strip()] += 1
    return top_response(counter)


def _cmd_thresholds() -> dict:
    from src.shared.adaptive_thresholds import adaptive_thresholds
    return thresholds_response(adaptive_thresholds.summary())


async def _do_rollback(build_id: str) -> dict:
    """Close the GitHub PR associated with build_id."""
    from src.shared.fix_memory import fix_memory

    pr_url = ""
    for rec in reversed(fix_memory._load_records()):  # pylint: disable=protected-access
        if rec.get("build_id") == build_id and not rec.get("_update"):
            pr_url = rec.get("pr_url", "")
            break

    if not pr_url or "github.com" not in pr_url:
        return usage(f"⚠️ No open PR found for build `{build_id}`. Nothing to rollback.")

    parts = pr_url.rstrip("/").split("/")
    try:
        pr_number = int(parts[-1])
        repo      = f"{parts[-4]}/{parts[-3]}"
    except (ValueError, IndexError):
        return usage(f"⚠️ Could not parse PR URL: {pr_url}")

    if not _GITHUB_TOKEN:
        return usage("⚠️ GITHUB_TOKEN not configured — cannot rollback automatically.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                headers={
                    "Authorization": f"token {_GITHUB_TOKEN}",
                    "Accept":        "application/vnd.github+json",
                },
                json={"state": "closed"},
            )
        if resp.status_code == 200:
            logger.info("rollback_success build_id=%s pr=%d repo=%s",
                        build_id, pr_number, repo)
            return {
                "response_type": "in_channel",
                "text": (
                    f"↩️ *Rollback complete* — PR #{pr_number} for build `{build_id}` "
                    f"has been closed.\n<{pr_url}|View PR>"
                ),
            }
        return usage(f"⚠️ GitHub returned {resp.status_code} — check manually: {pr_url}")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return usage(f"⚠️ Rollback error: {exc}")


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

async def handle_slash_command(request: web.Request) -> web.Response:
    """POST /webhooks/slack/commands — dispatch to the right sub-command."""
    body      = await request.read()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_signature(body, timestamp, signature):
        logger.warning("slack_slash_invalid_signature")
        return web.json_response({"error": "invalid_signature"}, status=403)

    try:
        form = await request.post()
    except Exception:  # pylint: disable=broad-exception-caught
        form = {}  # type: ignore[assignment]

    command = form.get("command", "")
    text    = (form.get("text") or "").strip()
    parts   = text.split()
    sub_cmd = parts[0].lower() if parts else "help"
    arg     = " ".join(parts[1:]) if len(parts) > 1 else ""

    logger.info("slack_slash command=%s sub=%s arg=%r", command, sub_cmd, arg)

    if sub_cmd == "status":     return web.json_response(_cmd_status(arg))
    if sub_cmd == "list":       return web.json_response(_cmd_list())
    if sub_cmd == "stats":      return web.json_response(_cmd_stats())
    if sub_cmd == "retry":      return web.json_response(await _cmd_retry(arg))
    if sub_cmd == "explain":    return web.json_response(_cmd_explain(arg))
    if sub_cmd == "history":    return web.json_response(_cmd_history(arg))
    if sub_cmd == "top":        return web.json_response(_cmd_top())
    if sub_cmd == "thresholds": return web.json_response(_cmd_thresholds())
    if sub_cmd == "rollback":
        if not arg:
            return web.json_response(usage("Usage: `/autoheal rollback <build_id>`"))
        return web.json_response(await _do_rollback(arg))

    return web.json_response(help_response())
