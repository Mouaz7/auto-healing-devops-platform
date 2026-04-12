"""Tests for Teams and Slack notifier render functions."""
from __future__ import annotations

import json

import pytest
import respx
import httpx

from src.notification_mcp.teams_notifier import render_card
from src.notification_mcp.slack_notifier import render_payload


class TestTeamsRenderCard:
    def test_green_card_contains_build_id(self):
        """GREEN card includes the build_id."""
        result = render_card("GREEN", "build-001", 0.95, "High confidence",
                             files="src/app.py", explanation="Fixed import")
        data = json.loads(result)
        body = data["attachments"][0]["content"]["body"]
        texts = [b["text"] for b in body]
        assert any("build-001" in t for t in texts)

    def test_green_card_includes_score_pct(self):
        """GREEN card shows score as percentage."""
        result = render_card("GREEN", "b1", 0.90, "reason")
        assert "90" in result

    def test_yellow_card_type(self):
        """YELLOW card has correct header."""
        result = render_card("YELLOW", "b2", 0.70, "needs review")
        data = json.loads(result)
        body = data["attachments"][0]["content"]["body"]
        header = body[0]["text"]
        assert "REVIEW" in header

    def test_red_card_has_manual_intervention(self):
        """RED card mentions manual intervention."""
        result = render_card("RED", "b3", 0.3, "Low confidence")
        assert "Manual" in result or "manual" in result.lower()

    def test_unknown_colour_falls_back_to_red(self):
        """Unknown colour → RED card template."""
        result = render_card("PURPLE", "b4", 0.5, "reason")
        data = json.loads(result)
        body = data["attachments"][0]["content"]["body"]
        assert any("BLOCKED" in b["text"] or "Manual" in b.get("text", "") for b in body)

    def test_explanation_substituted(self):
        """Explanation text is placed in the card."""
        result = render_card("GREEN", "b5", 0.88, "reason",
                             explanation="Fixed the missing import")
        assert "Fixed the missing import" in result

    def test_files_substituted(self):
        """Files list is placed in the card."""
        result = render_card("GREEN", "b6", 0.92, "reason",
                             files="src/main.py, src/lib.py")
        assert "src/main.py" in result


class TestSlackRenderPayload:
    def test_green_payload_has_auto_fix_header(self):
        """GREEN payload has 'Auto-fix Applied' header."""
        result = render_payload("GREEN", "b1", 0.95, "reason")
        data = json.loads(result)
        header_text = data["blocks"][0]["text"]["text"]
        assert "Auto-fix" in header_text

    def test_yellow_payload_has_review_header(self):
        """YELLOW payload has 'Review Required' header."""
        result = render_payload("YELLOW", "b2", 0.70, "reason")
        data = json.loads(result)
        header_text = data["blocks"][0]["text"]["text"]
        assert "Review" in header_text

    def test_red_payload_has_blocked_header(self):
        """RED payload has 'Fix Blocked' header."""
        result = render_payload("RED", "b3", 0.3, "reason")
        data = json.loads(result)
        header_text = data["blocks"][0]["text"]["text"]
        assert "Blocked" in header_text

    def test_build_id_in_payload(self):
        """build_id substituted into payload text."""
        result = render_payload("GREEN", "my-build-99", 0.88, "OK")
        assert "my-build-99" in result

    def test_score_pct_in_payload(self):
        """Score shown as integer percent."""
        result = render_payload("YELLOW", "b4", 0.75, "review")
        assert "75" in result

    def test_unknown_colour_falls_back_to_red(self):
        """Unknown colour uses RED template."""
        result = render_payload("ORANGE", "b5", 0.5, "reason")
        data = json.loads(result)
        header_text = data["blocks"][0]["text"]["text"]
        assert "Blocked" in header_text


class TestSendSlackNotification:
    """Tests for the HTTP send function in slack_notifier."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_returns_true_on_200(self, monkeypatch):
        """send_slack_notification returns True when webhook responds 200."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "http://hooks.slack.com/test")
        import importlib
        import src.notification_mcp.slack_notifier as sn
        importlib.reload(sn)

        respx.post("http://hooks.slack.com/test").mock(return_value=httpx.Response(200))
        result = await sn.send_slack_notification("GREEN", "b1", 0.9, "ok")
        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_returns_false_on_500(self, monkeypatch):
        """send_slack_notification returns False when webhook responds non-200."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "http://hooks.slack.com/test")
        import importlib
        import src.notification_mcp.slack_notifier as sn
        importlib.reload(sn)

        respx.post("http://hooks.slack.com/test").mock(return_value=httpx.Response(500))
        result = await sn.send_slack_notification("RED", "b2", 0.1, "fail")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_returns_false_when_no_url(self, monkeypatch):
        """send_slack_notification returns False when SLACK_WEBHOOK_URL not set."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
        import importlib
        import src.notification_mcp.slack_notifier as sn
        importlib.reload(sn)

        result = await sn.send_slack_notification("GREEN", "b1", 0.9, "ok")
        assert result is False


class TestSendTeamsNotification:
    """Tests for the HTTP send function in teams_notifier."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_returns_true_on_200(self, monkeypatch):
        """send_teams_notification returns True when webhook responds 200."""
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "http://teams.example.com/webhook")
        import importlib
        import src.notification_mcp.teams_notifier as tn
        importlib.reload(tn)

        respx.post("http://teams.example.com/webhook").mock(return_value=httpx.Response(200))
        result = await tn.send_teams_notification("GREEN", "b1", 0.9, "ok")
        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_returns_false_on_500(self, monkeypatch):
        """send_teams_notification returns False when webhook responds non-200."""
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "http://teams.example.com/webhook")
        import importlib
        import src.notification_mcp.teams_notifier as tn
        importlib.reload(tn)

        respx.post("http://teams.example.com/webhook").mock(return_value=httpx.Response(500))
        result = await tn.send_teams_notification("RED", "b2", 0.1, "fail")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_returns_false_when_no_url(self, monkeypatch):
        """send_teams_notification returns False when TEAMS_WEBHOOK_URL not set."""
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "")
        import importlib
        import src.notification_mcp.teams_notifier as tn
        importlib.reload(tn)

        result = await tn.send_teams_notification("GREEN", "b1", 0.9, "ok")
        assert result is False
