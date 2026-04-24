"""Slack slash-command handler for /autoheal.

Supported commands:
  /autoheal status  <build_id>   — current workflow status + score
  /autoheal list                 — last 10 workflows with colour
  /autoheal stats                — fix success rates by error type
  /autoheal retry  <build_id>   — re-submit a failed build to the pipeline
  /autoheal explain <build_id>  — plain-English AI explanation of the fix
  /autoheal rollback <build_id> — close the open PR (undo the fix)
  /autoheal history <file_path> — fix history for a specific source file
  /autoheal top                  — most problematic files this session
  /autoheal thresholds           — show adaptive confidence thresholds

All requests are verified with Slack's HMAC-SHA256 signature.
Responses are immediate (< 3 s) to avoid Slack timeout errors.

Env vars:
  SLACK_SIGNING_SECRET   — required for signature verification
  GITHUB_TOKEN           — required for rollback (PR close)
  ORCHESTRATOR_URL       — internal URL for retry (default: http://localhost:8085)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from collections import Counter
from typing import Any

import httpx
from aiohttp import web

logger = logging.getLogger(__name__)

_SIGNING_SECRET      = os.getenv("SLACK_SIGNING_SECRET", "")
_GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN", "")
_ORCHESTRATOR_URL    = os.getenv("ORCHESTRATOR_URL", "http://localhost:8085")
_REPLAY_WINDOW       = 300  # 5 minutes


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
    base     = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(_SIGNING_SECRET.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _status_response(build_id: str, state: Any) -> dict:
    if state is None:
        return {"response_type": "ephemeral", "text": f":x: Build `{build_id}` not found."}

    status = getattr(state, "status", None)
    status_val = status.value if hasattr(status, "value") else str(status)
    emoji = {"COMPLETED": "✅", "AWAITING_REVIEW": "🟡", "BLOCKED": "🔴",
             "GENERATING_FIX": "⚙️", "ANALYSING": "🔍", "PENDING": "⏳"}.get(status_val, "⚪")

    updated = getattr(state, "updated_at", None)
    updated_s = updated.strftime("%H:%M UTC") if updated else "—"
    error_msg = getattr(state, "error_message", "") or ""

    lines = [f"{emoji} *Build `{build_id}`*", f"Status: *{status_val}* | Updated: {updated_s}"]
    if error_msg:
        lines.append(f"Error: _{error_msg[:120]}_")

    return {
        "response_type": "ephemeral",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}],
    }


def _list_response(workflows: list[Any]) -> dict:
    if not workflows:
        return {"response_type": "ephemeral", "text": "No workflows found."}

    lines = ["*Recent workflows:*"]
    for wf in workflows[:10]:
        bid    = getattr(wf, "build_id", "?")
        status = getattr(wf, "status", None)
        sv     = status.value if hasattr(status, "value") else str(status)
        emoji  = {"COMPLETED": "✅", "AWAITING_REVIEW": "🟡", "BLOCKED": "🔴",
                  "GENERATING_FIX": "⚙️", "ANALYSING": "🔍"}.get(sv, "⚪")
        lines.append(f"{emoji} `{bid}` — {sv}")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def _stats_response(stats: dict) -> dict:
    if not stats:
        return {"response_type": "ephemeral", "text": "No fix history yet."}

    lines = ["*Fix success rates by error type:*"]
    for et, s in sorted(stats.items(), key=lambda kv: kv[1].get("total", 0), reverse=True):
        total  = s.get("total", 0)
        green  = int(s.get("green_rate", 0) * 100)
        yellow = int(s.get("yellow_rate", 0) * 100)
        red    = int(s.get("red_rate", 0) * 100)
        lines.append(f"• `{et}` — {total} fix(es) | 🟢 {green}% 🟡 {yellow}% 🔴 {red}%")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def _explain_response(build_id: str, records: list[dict]) -> dict:
    if not records:
        return {
            "response_type": "ephemeral",
            "text": f":x: No fix record found for build `{build_id}`.",
        }

    rec    = records[0]
    ts     = rec.get("ts", "")[:10]
    et     = rec.get("error_type", "UNKNOWN")
    cause  = rec.get("root_cause_short") or rec.get("root_cause", "—")
    expl   = rec.get("explanation", "No explanation available.")
    conf   = int(rec.get("confidence", 0) * 100)
    colour = rec.get("outcome", "?")
    files  = rec.get("files_key", "").replace(",", ", ") or "—"
    pr_url = rec.get("pr_url", "")
    approved = rec.get("approved")

    approved_s = ""
    if approved is True:
        approved_s = "\n✅ *Human approved and merged*"
    elif approved is False:
        approved_s = "\n❌ *Human rejected*"

    pr_s = f"\n🔗 <{pr_url}|View PR>" if pr_url else ""

    colour_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(colour, "⚪")

    text = (
        f"{colour_emoji} *Fix explanation for build `{build_id}`* ({ts})\n\n"
        f"*Error type:* `{et}` | *Confidence:* {conf}%\n"
        f"*Root cause:* {cause[:200]}\n"
        f"*Files changed:* `{files}`\n\n"
        f"*What the AI did:*\n_{expl[:400]}_"
        f"{approved_s}{pr_s}"
    )
    return {
        "response_type": "ephemeral",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def _history_response(file_path: str, records: list[dict]) -> dict:
    if not records:
        return {
            "response_type": "ephemeral",
            "text": f":x: No fix history found for `{file_path}`.",
        }

    lines = [f"*Fix history for `{file_path}`:*"]
    for rec in records[:8]:
        ts     = rec.get("ts", "")[:10]
        et     = rec.get("error_type", "?")
        conf   = int(rec.get("confidence", 0) * 100)
        colour = rec.get("outcome", "?")
        emoji  = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(colour, "⚪")
        approved = rec.get("approved")
        human = " ✅" if approved is True else (" ❌" if approved is False else "")
        lines.append(f"{emoji} `{ts}` — {et} ({conf}%){human}")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def _top_response(file_counter: Counter) -> dict:
    if not file_counter:
        return {"response_type": "ephemeral", "text": "No failure data yet."}

    lines = ["*Most troubled files (all time):*"]
    for f, n in file_counter.most_common(8):
        bar = "█" * min(n, 10)
        lines.append(f"• `{f}` — {n} failure(s)  {bar}")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def _thresholds_response(summary: dict) -> dict:
    if not summary:
        return {
            "response_type": "ephemeral",
            "text": "No adaptive threshold data yet — more human decisions needed.",
        }

    lines = ["*Adaptive confidence thresholds:*",
             "_Thresholds marked ★ have been self-adjusted from human decisions._\n"]
    for et, info in sorted(summary.items()):
        green  = int(info["green_threshold"] * 100)
        yellow = int(info["yellow_threshold"] * 100)
        star   = " ★" if info.get("adapted") else ""
        lines.append(f"• `{et}`{star} — GREEN ≥ {green}% | YELLOW ≥ {yellow}%")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

async def handle_slash_command(request: web.Request) -> web.Response:
    """Handle POST /webhooks/slack/commands."""
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

    # ---- status -------------------------------------------------------
    if sub_cmd == "status":
        if not arg:
            return web.json_response({"response_type": "ephemeral",
                                      "text": "Usage: `/autoheal status <build_id>`"})
        from src.orchestrator_mcp.workflow import WorkflowEngine
        engine = _get_engine()
        try:
            state = engine.get(arg) if engine else None
        except Exception:  # pylint: disable=broad-exception-caught
            state = None
        return web.json_response(_status_response(arg, state))

    # ---- list ---------------------------------------------------------
    if sub_cmd == "list":
        engine = _get_engine()
        active = engine.list_active() if engine else []
        return web.json_response(_list_response(active))

    # ---- stats --------------------------------------------------------
    if sub_cmd == "stats":
        from src.shared.fix_memory import fix_memory
        return web.json_response(_stats_response(fix_memory.stats()))

    # ---- retry --------------------------------------------------------
    if sub_cmd == "retry":
        if not arg:
            return web.json_response({"response_type": "ephemeral",
                                      "text": "Usage: `/autoheal retry <build_id>`"})
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                # Ask the orchestrator to re-queue; returns immediately with 202
                resp = await client.post(
                    f"{_ORCHESTRATOR_URL}/tools/retry_build",
                    json={"build_id": arg},
                )
            if resp.status_code in (200, 202):
                return web.json_response({
                    "response_type": "ephemeral",
                    "text": f"♻️ Build `{arg}` has been re-submitted to the pipeline.",
                })
            return web.json_response({
                "response_type": "ephemeral",
                "text": f"⚠️ Could not retry build `{arg}` (status {resp.status_code}).",
            })
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return web.json_response({
                "response_type": "ephemeral",
                "text": f"⚠️ Retry failed: {exc}",
            })

    # ---- explain ------------------------------------------------------
    if sub_cmd == "explain":
        if not arg:
            return web.json_response({"response_type": "ephemeral",
                                      "text": "Usage: `/autoheal explain <build_id>`"})
        from src.shared.fix_memory import fix_memory
        all_recs = fix_memory._load_records()
        matching = [r for r in all_recs if r.get("build_id") == arg and not r.get("_update")]
        return web.json_response(_explain_response(arg, matching))

    # ---- rollback -----------------------------------------------------
    if sub_cmd == "rollback":
        if not arg:
            return web.json_response({"response_type": "ephemeral",
                                      "text": "Usage: `/autoheal rollback <build_id>`"})
        return web.json_response(await _do_rollback(arg))

    # ---- history ------------------------------------------------------
    if sub_cmd == "history":
        if not arg:
            return web.json_response({"response_type": "ephemeral",
                                      "text": "Usage: `/autoheal history <file_path>`"})
        from src.shared.fix_memory import fix_memory
        all_recs = fix_memory._load_records()
        matching = [
            r for r in reversed(all_recs)
            if not r.get("_update") and arg in (r.get("files_key") or "")
        ]
        return web.json_response(_history_response(arg, matching))

    # ---- top ----------------------------------------------------------
    if sub_cmd == "top":
        from src.shared.fix_memory import fix_memory
        counter: Counter = Counter()
        for rec in fix_memory._load_records():
            if rec.get("_update"):
                continue
            for f in (rec.get("files_key") or "").split(","):
                if f.strip():
                    counter[f.strip()] += 1
        return web.json_response(_top_response(counter))

    # ---- thresholds ---------------------------------------------------
    if sub_cmd == "thresholds":
        from src.shared.adaptive_thresholds import adaptive_thresholds
        return web.json_response(_thresholds_response(adaptive_thresholds.summary()))

    # ---- help (default) -----------------------------------------------
    return web.json_response({
        "response_type": "ephemeral",
        "text": (
            "*Auto-Healer slash commands:*\n"
            "• `/autoheal status <build_id>` — workflow status\n"
            "• `/autoheal list` — recent workflows\n"
            "• `/autoheal stats` — fix success rates\n"
            "• `/autoheal retry <build_id>` — re-run a failed pipeline\n"
            "• `/autoheal explain <build_id>` — plain-English fix explanation\n"
            "• `/autoheal rollback <build_id>` — close/undo the fix PR\n"
            "• `/autoheal history <file>` — fix history for a file\n"
            "• `/autoheal top` — most troubled files\n"
            "• `/autoheal thresholds` — adaptive confidence thresholds"
        ),
    })


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


async def _do_rollback(build_id: str) -> dict:
    """Close the GitHub PR associated with build_id."""
    from src.shared.fix_memory import fix_memory

    all_recs = fix_memory._load_records()
    pr_url   = ""
    for rec in reversed(all_recs):
        if rec.get("build_id") == build_id and not rec.get("_update"):
            pr_url = rec.get("pr_url", "")
            break

    if not pr_url or "github.com" not in pr_url:
        return {
            "response_type": "ephemeral",
            "text": f"⚠️ No open PR found for build `{build_id}`. Nothing to rollback.",
        }

    # Extract repo and PR number from URL like https://github.com/owner/repo/pull/123
    parts = pr_url.rstrip("/").split("/")
    try:
        pr_number = int(parts[-1])
        repo      = f"{parts[-4]}/{parts[-3]}"
    except (ValueError, IndexError):
        return {"response_type": "ephemeral", "text": f"⚠️ Could not parse PR URL: {pr_url}"}

    if not _GITHUB_TOKEN:
        return {
            "response_type": "ephemeral",
            "text": "⚠️ GITHUB_TOKEN not configured — cannot rollback automatically.",
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                headers={
                    "Authorization": f"token {_GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
                json={"state": "closed"},
            )
        if resp.status_code == 200:
            logger.info("rollback_success build_id=%s pr=%d repo=%s", build_id, pr_number, repo)
            return {
                "response_type": "in_channel",
                "text": (
                    f"↩️ *Rollback complete* — PR #{pr_number} for build `{build_id}` "
                    f"has been closed.\n<{pr_url}|View PR>"
                ),
            }
        return {
            "response_type": "ephemeral",
            "text": f"⚠️ GitHub returned {resp.status_code} — check manually: {pr_url}",
        }
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return {"response_type": "ephemeral", "text": f"⚠️ Rollback error: {exc}"}
