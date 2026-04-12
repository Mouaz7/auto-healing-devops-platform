from __future__ import annotations

import json

import pytest

from src.notification_mcp.teams_notifier import render_card
from src.notification_mcp.slack_notifier import render_payload


class TestRenderCard:
    def test_green_card_contains_build_id(self):
        raw = render_card("GREEN", "build-42", 0.92, "reason", "src/a.py", "Added Foo")
        assert "build-42" in raw

    def test_green_card_contains_score(self):
        raw = render_card("GREEN", "b1", 0.92, "", "", "")
        assert "92" in raw  # 92%

    def test_yellow_card_contains_reason(self):
        raw = render_card("YELLOW", "b1", 0.72, "needs review", "", "")
        assert "needs review" in raw

    def test_red_card_contains_build_id(self):
        raw = render_card("RED", "build-99", 0.20, "HIGH blast radius", "", "")
        assert "build-99" in raw

    def test_unknown_colour_falls_back_to_red_template(self):
        raw = render_card("PURPLE", "b1", 0.5, "unknown", "", "")
        data = json.loads(raw)
        # Red template has "FIX BLOCKED" in it
        assert "BLOCKED" in raw

    def test_output_is_valid_json(self):
        raw = render_card("GREEN", "b1", 0.9, "ok", "file.py", "explanation")
        parsed = json.loads(raw)
        assert parsed["type"] == "message"

    def test_no_placeholder_tokens_remain(self):
        raw = render_card("GREEN", "b1", 0.9, "reason", "file.py", "expl")
        for placeholder in ["__BUILD_ID__", "__SCORE_PCT__", "__REASON__",
                             "__FILES__", "__EXPLANATION__"]:
            assert placeholder not in raw


class TestRenderPayload:
    def test_green_payload_contains_build_id(self):
        raw = render_payload("GREEN", "build-42", 0.92, "ok", "src/a.py", "Added Foo")
        assert "build-42" in raw

    def test_score_as_percentage(self):
        raw = render_payload("GREEN", "b1", 0.75, "", "", "")
        assert "75" in raw

    def test_red_payload_contains_reason(self):
        raw = render_payload("RED", "b1", 0.20, "LOW confidence", "", "")
        assert "LOW confidence" in raw

    def test_output_is_valid_json(self):
        raw = render_payload("YELLOW", "b1", 0.65, "review", "f.py", "expl")
        parsed = json.loads(raw)
        assert "blocks" in parsed

    def test_no_placeholder_tokens_remain(self):
        raw = render_payload("RED", "b1", 0.1, "reason", "file.py", "expl")
        for placeholder in ["__BUILD_ID__", "__SCORE_PCT__", "__REASON__",
                             "__FILES__", "__EXPLANATION__"]:
            assert placeholder not in raw

    def test_unknown_colour_falls_back_to_red(self):
        raw = render_payload("ORANGE", "b1", 0.5, "x", "", "")
        assert "Blocked" in raw or "blocked" in raw.lower() or "Manual" in raw
