"""Microsoft Teams notifier — fixed Adaptive Card templates.

Templates are module-level constants. Payload values are substituted via
string replacement so that log content cannot inject JSON structure.
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments,duplicate-code
from __future__ import annotations

import copy
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

# Fixed Adaptive Card templates — never built dynamically
_CARD_TEMPLATES: dict[str, dict] = {
    "GREEN": {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "body": [
                    {"type": "TextBlock", "text": "AUTO-FIX APPLIED",
                     "weight": "Bolder", "size": "Large"},
                    {"type": "TextBlock", "text": "Build: __BUILD_ID__"},
                    {"type": "TextBlock", "text": "Confidence: __SCORE_PCT__%"},
                    {"type": "TextBlock", "text": "Files: __FILES__"},
                    {"type": "TextBlock", "text": "__EXPLANATION__"},
                ],
            },
        }],
    },
    "YELLOW": {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "body": [
                    {"type": "TextBlock", "text": "REVIEW REQUIRED",
                     "weight": "Bolder", "size": "Large"},
                    {"type": "TextBlock", "text": "Build: __BUILD_ID__"},
                    {"type": "TextBlock", "text": "Confidence: __SCORE_PCT__%"},
                    {"type": "TextBlock", "text": "Files: __FILES__"},
                    {"type": "TextBlock", "text": "Reason: __REASON__"},
                    {"type": "TextBlock", "text": "__EXPLANATION__"},
                ],
            },
        }],
    },
    "RED": {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "body": [
                    {"type": "TextBlock", "text": "FIX BLOCKED",
                     "weight": "Bolder", "size": "Large"},
                    {"type": "TextBlock", "text": "Build: __BUILD_ID__"},
                    {"type": "TextBlock", "text": "Files: __FILES__"},
                    {"type": "TextBlock", "text": "Reason: __REASON__"},
                    {"type": "TextBlock", "text": "Action: Manual intervention required"},
                ],
            },
        }],
    },
}


def render_card(colour: str, build_id: str, score: float,
                reason: str, files: str = "", explanation: str = "") -> str:
    """Render a Teams Adaptive Card as a JSON string."""
    template = copy.deepcopy(_CARD_TEMPLATES.get(colour, _CARD_TEMPLATES["RED"]))
    raw = json.dumps(template)
    raw = raw.replace("__BUILD_ID__",    build_id)
    raw = raw.replace("__SCORE_PCT__",   str(round(score * 100)))
    raw = raw.replace("__REASON__",      reason)
    raw = raw.replace("__FILES__",       files)
    raw = raw.replace("__EXPLANATION__", explanation)
    return raw


async def send_teams_notification(  # pylint: disable=duplicate-code
    colour: str, build_id: str, score: float, reason: str,
    files: str = "", explanation: str = "",
) -> bool:
    """POST an Adaptive Card to the Teams webhook. Returns True on success."""
    if not _TEAMS_WEBHOOK_URL:
        logger.debug("teams_notify skipped — TEAMS_WEBHOOK_URL not set")
        return False
    payload = render_card(colour, build_id, score, reason, files, explanation)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _TEAMS_WEBHOOK_URL, content=payload,
            headers={"Content-Type": "application/json"},
        )
        ok = resp.status_code == 200
        logger.info("teams_notify build_id=%s colour=%s ok=%s", build_id, colour, ok)
        return ok
