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
             "text": {"type": "plain_text", "text": "✅ Auto-fix Proposed (Review Required)"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "*Build:* __BUILD_ID__\n*Confidence:* __SCORE_PCT__%\n"
                              "*Files:* __FILES__\n*Duration:* __DURATION__\n__EXPLANATION__"}},
        ],
    },
    "YELLOW": {
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🟡 Human Review Required"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "*Build:* __BUILD_ID__\n*Confidence:* __SCORE_PCT__%\n"
                              "*Files:* __FILES__\n*Duration:* __DURATION__\n"
                              "*Reason:* __REASON__\n__EXPLANATION__"}},
        ],
    },
    "RED": {
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🔴 Fix Blocked"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "*Build:* __BUILD_ID__\n*Files:* __FILES__\n"
                              "*Duration:* __DURATION__\n*Reason:* __REASON__\n"
                              "Manual intervention required."}},
        ],
    },
}


def _format_duration(elapsed_s: int) -> str:
    if elapsed_s <= 0:
        return "—"
    if elapsed_s < 60:
        return f"{elapsed_s}s"
    return f"{elapsed_s // 60}m {elapsed_s % 60}s"


def render_payload(colour: str, build_id: str, score: float,
                   reason: str, files: str = "", explanation: str = "",
                   elapsed_s: int = 0) -> str:
    """Render a Slack Block Kit payload as a JSON string."""
    template = copy.deepcopy(_SLACK_TEMPLATES.get(colour, _SLACK_TEMPLATES["RED"]))
    raw = json.dumps(template)
    raw = raw.replace("__BUILD_ID__",    build_id)
    raw = raw.replace("__SCORE_PCT__",   str(round(score * 100)))
    raw = raw.replace("__REASON__",      reason)
    raw = raw.replace("__FILES__",       files)
    raw = raw.replace("__DURATION__",    _format_duration(elapsed_s))
    raw = raw.replace("__EXPLANATION__", explanation)
    return raw


async def send_slack_review_buttons(
    build_id: str,
    pr_url: str,
    pr_number: int,
    repo: str,
    score: float,
    explanation: str = "",
    report_data: dict | None = None,
) -> bool:
    """Send detailed review message with Approve/Reject buttons to Slack."""
    if not _SLACK_WEBHOOK_URL:
        return False

    rd = report_data or {}
    score_pct    = round(score * 100)
    error_t      = rd.get("error_type", "—")
    blast        = rd.get("blast_radius", "—")
    root_c       = rd.get("root_cause", "—")
    scan_findings= rd.get("scan_findings", [])
    bug_count    = rd.get("bug_count", 0) or len(scan_findings)
    elapsed      = rd.get("elapsed_s", 0)
    dur          = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else (f"{elapsed}s" if elapsed else "—")
    colour       = rd.get("colour", "GREEN")
    conf_bar     = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)

    # Build bug findings text for Slack (with line numbers)
    if scan_findings:
        sev_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "INFO": "🔵"}
        bug_lines = []
        for i, f in enumerate(scan_findings[:8], 1):
            icon = sev_icon.get(f.get("severity", "HIGH"), "🔴")
            fix_hint = f"  → Fix: {f['suggestion']}" if f.get("suggestion") else ""
            bug_lines.append(
                f"{i}. {icon} *Line {f['line']}* — `{f['pattern']}` ({f.get('severity','HIGH')})\n"
                f"   _{f['message'][:120]}_{fix_hint}"
            )
        if len(scan_findings) > 8:
            bug_lines.append(f"_...and {len(scan_findings) - 8} more bugs (see PR for full list)_")
        bug_text = "\n".join(bug_lines)
    else:
        bug_text = "_(No bugs found by static scanner)_"

    # Short before/after snippet (first 10 lines of each)
    original_code = rd.get("original_code", "")
    fix_patch     = rd.get("fix_patch", "")
    orig_snippet  = "\n".join(original_code.splitlines()[:10]) if original_code else ""
    fix_snippet   = "\n".join(fix_patch.splitlines()[:10]) if fix_patch else ""

    colour_label = {"GREEN": "✅ Auto-Fix Ready", "YELLOW": "🟡 Auto-Fix Ready"}.get(colour, "🤖 Auto-Fix Ready")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{colour_label} — Human Review Required"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Build:* `{build_id}`\n"
                    f"*Confidence:* {score_pct}% `{conf_bar}`\n"
                    f"*Time to fix:* {dur}\n"
                    f"*PR:* <{pr_url}|View on GitHub>"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*🔍 Error Analysis*\n"
                    f"• *Error Type:* `{error_t}`\n"
                    f"• *Blast Radius:* `{blast}`\n"
                    f"• *Root Cause:* {root_c[:200]}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🐛 Bugs Found — {bug_count} bug(s) with exact line numbers*\n{bug_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🛠️ What was fixed*\n{explanation[:400]}",
            },
        },
    ]

    # Add before/after snippets if available
    if orig_snippet or fix_snippet:
        blocks.append({"type": "divider"})
        if orig_snippet:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🔴 Code BEFORE (buggy — first 10 lines)*\n```{orig_snippet}```",
                },
            })
        if fix_snippet:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*✅ Code AFTER (fixed — first 10 lines)*\n```{fix_snippet}```",
                },
            })

    blocks += [
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

    payload = {"blocks": blocks}

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
    files: str = "", explanation: str = "", elapsed_s: int = 0,
) -> bool:
    """POST a Block Kit message to the Slack webhook. Returns True on success."""
    if not _SLACK_WEBHOOK_URL:
        logger.debug("slack_notify skipped — SLACK_WEBHOOK_URL not set")
        return False
    payload = render_payload(colour, build_id, score, reason, files, explanation,
                             elapsed_s=elapsed_s)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _SLACK_WEBHOOK_URL, content=payload,
            headers={"Content-Type": "application/json"},
        )
        ok = resp.status_code == 200
        logger.info("slack_notify build_id=%s colour=%s ok=%s", build_id, colour, ok)
        return ok


async def send_slack_pipeline_started(
    build_id: str, repo: str = "", files: list[str] | None = None
) -> bool:
    """Send an immediate "started" Slack notice so the user sees that auto-heal
    is working. The final GREEN/YELLOW/RED message follows when the pipeline
    completes (can take 5-20 min for hard cases — without this, the user has
    no visibility during the wait).
    """
    if not _SLACK_WEBHOOK_URL:
        return False
    repo_line  = f"*Repo:* `{repo}`\n" if repo else ""
    files_line = ("*Files:* " + ", ".join(f"`{f}`" for f in files) + "\n") if files else ""
    payload = json.dumps({
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "⚙️ Auto-heal Started"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": (f"*Build:* `{build_id}`\n{repo_line}{files_line}"
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
