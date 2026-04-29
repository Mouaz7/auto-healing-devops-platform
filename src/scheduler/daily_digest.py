"""Daily intelligence digest — sends a morning Slack summary.

Runs once per day (default: 08:00 UTC) and posts a rich Slack Block Kit
message with:
  • Total builds processed today / this week
  • Fix success rate (GREEN %)
  • Top 3 most common error types
  • Files that fail most often ("most troubled files")
  • Estimated tokens saved by log compression
  • Estimated API cost today
  • Adaptive threshold changes from human decisions
  • Recommendation (e.g. "Consider adding tests for src/payments.py")

This gives engineering teams a daily intelligence briefing about their
CI/CD health without having to look at dashboards.

Usage (standalone):
    python -m src.scheduler.daily_digest

Usage (from scheduler):
    digest = DailyDigest()
    await digest.send()

Env vars:
  SLACK_WEBHOOK_URL  — where to post the digest
  DIGEST_HOUR_UTC    — hour to send (default: 8)
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import datetime, UTC

import httpx

logger = logging.getLogger(__name__)

_SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
_DIGEST_HOUR   = int(os.getenv("DIGEST_HOUR_UTC", "8"))


class DailyDigest:
    """Build and send a daily Slack intelligence digest."""

    async def send(self) -> bool:
        """Collect stats, format, and POST to Slack.

        Returns:
            True if Slack accepted the message.
        """
        blocks = self._build_blocks()
        if not _SLACK_WEBHOOK:
            logger.warning("daily_digest_skipped no SLACK_WEBHOOK_URL configured")
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    _SLACK_WEBHOOK,
                    json={"blocks": blocks},
                )
            ok = resp.status_code == 200
            if ok:
                logger.info("daily_digest_sent status=%d", resp.status_code)
            else:
                logger.warning("daily_digest_failed status=%d body=%s",
                               resp.status_code, resp.text[:200])
            return ok
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("daily_digest_error error=%s", exc)
            return False

    def _build_blocks(self) -> list[dict]:
        """Assemble Slack Block Kit blocks from current stats."""
        from src.shared.fix_memory import fix_memory
        from src.shared.cost_tracker import cost_tracker
        from src.shared.adaptive_thresholds import adaptive_thresholds
        from src.shared.heal_verifier import heal_verifier

        today = datetime.now(UTC).strftime("%A, %B %-d")
        stats = fix_memory.stats()
        cost  = cost_tracker.session_summary()

        # Aggregate totals
        total_builds = sum(s.get("total", 0) for s in stats.values())
        total_green  = sum(int(s.get("green_rate", 0) * s.get("total", 0)) for s in stats.values())
        total_yellow = sum(int(s.get("yellow_rate", 0) * s.get("total", 0)) for s in stats.values())
        total_red    = sum(int(s.get("red_rate", 0) * s.get("total", 0)) for s in stats.values())
        green_pct    = round(total_green / total_builds * 100) if total_builds else 0

        # Top error types
        top_errors = sorted(stats.items(), key=lambda kv: kv[1].get("total", 0), reverse=True)[:3]
        top_lines  = "\n".join(
            f"  • `{et}` — {s['total']} occurrences (🟢 {int(s['green_rate']*100)}%)"
            for et, s in top_errors
        ) or "  _No failures recorded yet._"

        # Most troubled files (from fix_memory records)
        file_counter: Counter = Counter()
        for rec in fix_memory._load_records():
            if rec.get("_update"):
                continue
            for f in (rec.get("files_key") or "").split(","):
                if f.strip():
                    file_counter[f.strip()] += 1
        troubled = file_counter.most_common(3)
        troubled_lines = "\n".join(
            f"  • `{f}` — {n} failures" for f, n in troubled
        ) or "  _All files healthy._"

        # Adaptive thresholds summary
        threshold_summary = adaptive_thresholds.summary()
        adapted = [et for et, info in threshold_summary.items() if info.get("adapted")]
        threshold_text = (
            f"  _{len(adapted)} error type(s) with self-adjusted thresholds: "
            + ", ".join(f"`{t}`" for t in adapted[:3]) + "_"
        ) if adapted else "  _No threshold adaptations yet — collecting data._"

        # Active regression watches
        active_fixes = heal_verifier.active_fixes()
        regression_text = (
            f"  🔍 Watching *{len(active_fixes)}* recently deployed fix(es) for regressions."
            if active_fixes else
            "  ✅ No deployed fixes in regression watch window."
        )

        # Cost
        cost_usd = cost.get("session_total_usd", 0.0)
        avg_usd  = cost.get("avg_cost_per_build_usd", 0.0)

        # Recommendation
        recommendation = self._generate_recommendation(stats, troubled, green_pct)

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🤖 Auto-Healer Daily Report — {today}"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Builds processed:*\n{total_builds}"},
                    {"type": "mrkdwn", "text": f"*Auto-fix rate (GREEN):*\n🟢 {green_pct}%"},
                    {"type": "mrkdwn", "text": f"*Human reviews sent:*\n🟡 {total_yellow}"},
                    {"type": "mrkdwn", "text": f"*Blocked (RED):*\n🔴 {total_red}"},
                    {"type": "mrkdwn", "text": f"*API cost (session):*\n${cost_usd:.4f}"},
                    {"type": "mrkdwn", "text": f"*Avg cost per build:*\n${avg_usd:.4f}"},
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*📊 Top Error Types:*\n{top_lines}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🗂️ Most Troubled Files:*\n{troubled_lines}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🧠 Adaptive Thresholds:*\n{threshold_text}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🔍 Regression Monitor:*\n{regression_text}"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💡 Recommendation:*\n{recommendation}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Use `/autoheal stats` for details · `/autoheal list` to see active workflows",
                    }
                ],
            },
        ]
        return blocks

    @staticmethod
    def _generate_recommendation(
        stats: dict,
        troubled: list[tuple[str, int]],
        green_pct: int,
    ) -> str:
        """Generate a plain-English recommendation based on the data."""
        if not stats:
            return "No data yet — trigger a build failure to see the system in action."

        if green_pct < 50:
            return (
                "⚠️ Auto-fix rate is below 50%. Consider reviewing the error types "
                "with HIGH blast radius — those always require manual fixes."
            )
        if troubled and troubled[0][1] >= 3:
            worst_file = troubled[0][0]
            return (
                f"📌 `{worst_file}` has failed {troubled[0][1]} times recently. "
                "Consider adding stronger unit tests or refactoring this module."
            )
        if green_pct >= 85:
            return (
                "🎉 Excellent! Auto-fix rate ≥ 85%. The AI is handling most failures "
                "autonomously. Continue monitoring adaptive thresholds."
            )
        return (
            f"📈 Auto-fix rate is {green_pct}%. "
            "Review rejected fixes in fix memory to improve confidence patterns."
        )


