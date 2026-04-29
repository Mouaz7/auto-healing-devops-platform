"""Tests for async resilience utilities — trigger_global_fallback."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.shared.resilience import trigger_global_fallback


class TestTriggerGlobalFallback:
    @respx.mock
    @pytest.mark.asyncio
    async def test_posts_red_payload(self):
        """trigger_global_fallback sends a RED payload to Agent 6."""
        route = respx.post("http://localhost:8087/tools/evaluate_and_notify").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await trigger_global_fallback("test_agent", "build-001", "crash")
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_agent6_unreachable_does_not_raise(self):
        """Network error to Agent 6 is silently logged, not raised."""
        respx.post("http://localhost:8087/tools/evaluate_and_notify").mock(
            side_effect=httpx.ConnectError("refused")
        )
        # Must not raise
        await trigger_global_fallback("agent", "build-002", "refused")

    @respx.mock
    @pytest.mark.asyncio
    async def test_payload_has_red_status(self):
        """Payload sent to Agent 6 has status=RED."""
        import json as _json
        captured = []

        async def capture(request, route):
            captured.append(_json.loads(request.content))
            return httpx.Response(200, json={})

        respx.post("http://localhost:8087/tools/evaluate_and_notify").mock(
            side_effect=capture
        )
        await trigger_global_fallback("agent5", "build-xyz", "timeout")
        assert captured[0]["status"] == "RED"
        assert captured[0]["build_id"] == "build-xyz"
        assert captured[0]["confidence"] == 0.0
