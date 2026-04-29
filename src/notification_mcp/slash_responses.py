"""Slack response builders for /autoheal slash commands.

Each function takes domain data and returns the dict Slack expects. Pure
formatting — no I/O, no global state.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


_STATUS_EMOJI = {
    "COMPLETED":       "✅",
    "AWAITING_REVIEW": "🟡",
    "BLOCKED":         "🔴",
    "GENERATING_FIX":  "⚙️",
    "ANALYSING":       "🔍",
    "PENDING":         "⏳",
}
_COLOUR_EMOJI = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}


def status_response(build_id: str, state: Any) -> dict:
    if state is None:
        return {"response_type": "ephemeral",
                "text": f":x: Build `{build_id}` not found."}

    status = getattr(state, "status", None)
    status_val = status.value if hasattr(status, "value") else str(status)
    emoji = _STATUS_EMOJI.get(status_val, "⚪")

    updated = getattr(state, "updated_at", None)
    updated_s = updated.strftime("%H:%M UTC") if updated else "—"
    error_msg = getattr(state, "error_message", "") or ""

    lines = [f"{emoji} *Build `{build_id}`*",
             f"Status: *{status_val}* | Updated: {updated_s}"]
    if error_msg:
        lines.append(f"Error: _{error_msg[:120]}_")

    return {
        "response_type": "ephemeral",
        "blocks": [{"type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)}}],
    }


def list_response(workflows: list[Any]) -> dict:
    if not workflows:
        return {"response_type": "ephemeral", "text": "No workflows found."}

    lines = ["*Recent workflows:*"]
    for wf in workflows[:10]:
        bid    = getattr(wf, "build_id", "?")
        status = getattr(wf, "status", None)
        sv     = status.value if hasattr(status, "value") else str(status)
        emoji  = _STATUS_EMOJI.get(sv, "⚪")
        lines.append(f"{emoji} `{bid}` — {sv}")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def stats_response(stats: dict) -> dict:
    if not stats:
        return {"response_type": "ephemeral", "text": "No fix history yet."}

    lines = ["*Fix success rates by error type:*"]
    for et, s in sorted(stats.items(), key=lambda kv: kv[1].get("total", 0), reverse=True):
        total  = s.get("total", 0)
        green  = int(s.get("green_rate",  0) * 100)
        yellow = int(s.get("yellow_rate", 0) * 100)
        red    = int(s.get("red_rate",    0) * 100)
        lines.append(f"• `{et}` — {total} fix(es) | 🟢 {green}% 🟡 {yellow}% 🔴 {red}%")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def explain_response(build_id: str, records: list[dict]) -> dict:
    if not records:
        return {"response_type": "ephemeral",
                "text": f":x: No fix record found for build `{build_id}`."}

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

    if approved is True:
        approved_s = "\n✅ *Human approved and merged*"
    elif approved is False:
        approved_s = "\n❌ *Human rejected*"
    else:
        approved_s = ""

    pr_s = f"\n🔗 <{pr_url}|View PR>" if pr_url else ""
    colour_emoji = _COLOUR_EMOJI.get(colour, "⚪")

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


def history_response(file_path: str, records: list[dict]) -> dict:
    if not records:
        return {"response_type": "ephemeral",
                "text": f":x: No fix history found for `{file_path}`."}

    lines = [f"*Fix history for `{file_path}`:*"]
    for rec in records[:8]:
        ts     = rec.get("ts", "")[:10]
        et     = rec.get("error_type", "?")
        conf   = int(rec.get("confidence", 0) * 100)
        colour = rec.get("outcome", "?")
        emoji  = _COLOUR_EMOJI.get(colour, "⚪")
        approved = rec.get("approved")
        human = " ✅" if approved is True else (" ❌" if approved is False else "")
        lines.append(f"{emoji} `{ts}` — {et} ({conf}%){human}")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def top_response(file_counter: Counter) -> dict:
    if not file_counter:
        return {"response_type": "ephemeral", "text": "No failure data yet."}

    lines = ["*Most troubled files (all time):*"]
    for f, n in file_counter.most_common(8):
        bar = "█" * min(n, 10)
        lines.append(f"• `{f}` — {n} failure(s)  {bar}")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def thresholds_response(summary: dict) -> dict:
    if not summary:
        return {"response_type": "ephemeral",
                "text": "No adaptive threshold data yet — more human decisions needed."}

    lines = ["*Adaptive confidence thresholds:*",
             "_Thresholds marked ★ have been self-adjusted from human decisions._\n"]
    for et, info in sorted(summary.items()):
        green  = int(info["green_threshold"]  * 100)
        yellow = int(info["yellow_threshold"] * 100)
        star   = " ★" if info.get("adapted") else ""
        lines.append(f"• `{et}`{star} — GREEN ≥ {green}% | YELLOW ≥ {yellow}%")

    return {"response_type": "ephemeral", "text": "\n".join(lines)}


def help_response() -> dict:
    return {
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
    }


def usage(text: str) -> dict:
    """Build a one-line ephemeral usage hint."""
    return {"response_type": "ephemeral", "text": text}
