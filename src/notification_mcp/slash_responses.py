"""Slack response builders for /autoheal slash commands.

Each function takes domain data and returns the dict Slack expects.
All responses use Block Kit with rich formatting and emoji indicators.
"""
from __future__ import annotations

import re
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


def clean_build_id(arg: str) -> str:
    """Strip common prefixes users accidentally include (build, #, id:, etc.)."""
    cleaned = arg.strip()
    cleaned = re.sub(r"^(build[_:#\s-]*|id[:\s]*|#)+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip("`'\"<> ")
    return cleaned


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _divider() -> dict:
    return {"type": "divider"}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _error(title: str, hint: str = "") -> dict:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"❌  {title}"}},
    ]
    if hint:
        blocks.append(_section(f"💡 *Tip:* {hint}"))
    blocks.append(_context("🤖 Run `/autoheal help` to see all commands"))
    return {"response_type": "ephemeral", "blocks": blocks}


def _footer() -> dict:
    return _context("🤖 Auto-Heal Bot  •  `/autoheal help` for all commands")


def status_response(build_id: str, state: Any) -> dict:
    build_id = clean_build_id(build_id)
    if not build_id:
        return _error(
            "Missing build ID",
            "Try `/autoheal status 25643594071` (paste the build number — no prefix needed)",
        )
    if state is None:
        return _error(
            f"Build `{build_id}` not found",
            "Use `/autoheal list` to see active builds, or check the Jenkins build number is correct.",
        )

    status = getattr(state, "status", None)
    status_val = status.value if hasattr(status, "value") else str(status)
    emoji = _STATUS_EMOJI.get(status_val, "⚪")

    updated = getattr(state, "updated_at", None)
    updated_s = updated.strftime("%H:%M UTC") if updated else "—"
    error_msg = getattr(state, "error_message", "") or ""

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"{emoji}  Build Status"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"🆔 *Build*\n`{build_id}`"},
            {"type": "mrkdwn", "text": f"📊 *Status*\n*{status_val}*"},
            {"type": "mrkdwn", "text": f"🕒 *Updated*\n{updated_s}"},
            {"type": "mrkdwn", "text": f"🚦 *State*\n{emoji} {status_val}"},
        ]},
    ]
    if error_msg:
        blocks.append(_section(f"⚠️ *Error*\n_{error_msg[:200]}_"))
    return {"response_type": "ephemeral", "blocks": blocks}


def list_response(workflows: list[Any]) -> dict:
    if not workflows:
        return {
            "response_type": "ephemeral",
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text", "text": "📋  Active Workflows"}},
                _section("_No workflows running right now._ 😴"),
                _context("💡 Trigger a Jenkins build failure to see the auto-heal pipeline in action."),
            ],
        }

    rows = []
    for wf in workflows[:10]:
        bid = getattr(wf, "build_id", "?")
        status = getattr(wf, "status", None)
        sv = status.value if hasattr(status, "value") else str(status)
        emoji = _STATUS_EMOJI.get(sv, "⚪")
        rows.append(f"{emoji}  `{bid}` — *{sv}*")

    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": f"📋  Active Workflows ({len(workflows)})"}},
            _section("\n".join(rows)),
            _context("🔍 Run `/autoheal status <build_id>` for details on any build."),
        ],
    }


def stats_response(stats: dict) -> dict:
    if not stats:
        return {
            "response_type": "ephemeral",
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text", "text": "📈  Fix Success Rates"}},
                _section("_No fix history yet._ 📭"),
            ],
        }

    rows = []
    for et, s in sorted(stats.items(), key=lambda kv: kv[1].get("total", 0), reverse=True):
        total  = s.get("total", 0)
        green  = int(s.get("green_rate",  0) * 100)
        yellow = int(s.get("yellow_rate", 0) * 100)
        red    = int(s.get("red_rate",    0) * 100)
        rows.append(
            f"🐛 `{et}` — *{total}* fix(es)\n"
            f"     🟢 {green}%   🟡 {yellow}%   🔴 {red}%"
        )

    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "📈  Fix Success Rates by Error Type"}},
            _section("\n\n".join(rows)),
            _context("📊 Statistics from all fixes recorded in fix_memory."),
        ],
    }


def explain_response(build_id: str, records: list[dict]) -> dict:
    build_id = clean_build_id(build_id)
    if not build_id:
        return _error(
            "Missing build ID",
            "Try `/autoheal explain 25643594071`",
        )
    if not records:
        return _error(
            f"No fix record for `{build_id}`",
            "The build may not have produced a fix yet, or the record has expired.",
        )

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
    colour_emoji = _COLOUR_EMOJI.get(colour, "⚪")

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"{colour_emoji}  Fix Explanation"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"🆔 *Build*\n`{build_id}`"},
            {"type": "mrkdwn", "text": f"📅 *Date*\n{ts}"},
            {"type": "mrkdwn", "text": f"📁 *Error Type*\n`{et}`"},
            {"type": "mrkdwn", "text": f"📊 *Confidence*\n{conf}%"},
        ]},
        _section(f"🔍 *Root Cause*\n> {cause[:250]}"),
        _section(f"📝 *Files Changed*\n`{files}`"),
        _divider(),
        _section(f"🛠️ *What the AI did*\n_{expl[:500]}_"),
    ]

    if approved is True:
        blocks.append(_section("✅ *Human approved and merged*"))
    elif approved is False:
        blocks.append(_section("❌ *Human rejected the fix*"))

    if pr_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "🔗  View PR on GitHub"},
                "url": pr_url,
            }],
        })

    return {"response_type": "ephemeral", "blocks": blocks}


def history_response(file_path: str, records: list[dict]) -> dict:
    file_path = file_path.strip("`'\" ")
    if not file_path:
        return _error(
            "Missing file path",
            "Try `/autoheal history src/quicksort.py`",
        )
    if not records:
        return _error(
            f"No fix history for `{file_path}`",
            "This file hasn't been auto-healed yet.",
        )

    rows = []
    for rec in records[:8]:
        ts     = rec.get("ts", "")[:10]
        et     = rec.get("error_type", "?")
        conf   = int(rec.get("confidence", 0) * 100)
        colour = rec.get("outcome", "?")
        emoji  = _COLOUR_EMOJI.get(colour, "⚪")
        approved = rec.get("approved")
        human = " ✅ approved" if approved is True else (" ❌ rejected" if approved is False else "")
        rows.append(f"{emoji}  `{ts}` — *{et}* ({conf}%){human}")

    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "📜  Fix History"}},
            _section(f"📁 *File:* `{file_path}`\n_Last {len(records[:8])} fix(es):_"),
            _section("\n".join(rows)),
        ],
    }


def top_response(file_counter: Counter) -> dict:
    if not file_counter:
        return {
            "response_type": "ephemeral",
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text", "text": "🏆  Most Troubled Files"}},
                _section("_No failure data yet._ 🌱"),
            ],
        }

    rows = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (f, n) in enumerate(file_counter.most_common(8)):
        prefix = medals[i] if i < 3 else "📁"
        bar = "🔴" * min(n, 10)
        rows.append(f"{prefix}  `{f}` — *{n}* failure(s)  {bar}")

    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🏆  Most Troubled Files"}},
            _section("\n".join(rows)),
            _context("🎯 These files might benefit from refactoring or extra test coverage."),
        ],
    }


def thresholds_response(summary: dict) -> dict:
    if not summary:
        return {
            "response_type": "ephemeral",
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text", "text": "🎚️  Adaptive Thresholds"}},
                _section("_No adaptive threshold data yet — need 5+ human decisions per error type._ 📊"),
            ],
        }

    rows = []
    for et, info in sorted(summary.items()):
        green  = int(info["green_threshold"]  * 100)
        yellow = int(info["yellow_threshold"] * 100)
        star   = " ⭐" if info.get("adapted") else ""
        rows.append(f"🐛 `{et}`{star}\n     🟢 GREEN ≥ {green}%   |   🟡 YELLOW ≥ {yellow}%")

    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🎚️  Adaptive Confidence Thresholds"}},
            _section("\n\n".join(rows)),
            _context("⭐ = self-adjusted from human decisions  •  Defaults: GREEN ≥ 85%, YELLOW ≥ 60%"),
        ],
    }


def help_response() -> dict:
    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "🤖  Auto-Heal Bot — Commands"}},
            _section(
                "*🔍 Inspect a build*\n"
                "• `/autoheal status <build_id>` — current workflow status\n"
                "• `/autoheal explain <build_id>` — plain-English fix explanation\n"
                "• `/autoheal list` — show active workflows"
            ),
            _section(
                "*♻️ Take action*\n"
                "• `/autoheal retry <build_id>` — re-submit a failed build\n"
                "• `/autoheal rollback <build_id>` — close the fix PR (undo)"
            ),
            _section(
                "*📊 Insights & history*\n"
                "• `/autoheal stats` — fix success rates by error type\n"
                "• `/autoheal history <file>` — fix history for a specific file\n"
                "• `/autoheal top` — most failure-prone files\n"
                "• `/autoheal thresholds` — adaptive confidence thresholds"
            ),
            _divider(),
            _context(
                "💡 *Tip:* Build IDs work with or without prefixes — "
                "`status 12345`, `status build 12345`, `status #12345` all work."
            ),
        ],
    }


def usage(text: str) -> dict:
    """Build a one-line ephemeral usage hint."""
    return {"response_type": "ephemeral", "text": text}
