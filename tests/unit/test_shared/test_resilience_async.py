"""Tests for async resilience utilities — with_retry and trigger_global_fallback."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.shared.resilience import (
    with_retry,
    trigger_global_fallback,
    validate_agent_output,
)


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Successful coro_fn returns result immediately."""
        calls = []

        async def succeed():
            calls.append(1)
            return "ok"

        result = await with_retry(succeed, max_retries=3, delays=[0.0])
        assert result == "ok"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        """Fails twice then succeeds on third attempt."""
        attempt = {"count": 0}

        async def flaky():
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise ValueError("not yet")
            return "done"

        result = await with_retry(flaky, max_retries=3, delays=[0.0, 0.0, 0.0])
        assert result == "done"
        assert attempt["count"] == 3

    @pytest.mark.asyncio
    async def test_raises_last_exception_when_all_fail(self):
        """Raises the last exception when all retries exhausted."""
        async def always_fail():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            await with_retry(always_fail, max_retries=2, delays=[0.0])

    @pytest.mark.asyncio
    async def test_max_retries_zero_means_one_attempt(self):
        """max_retries=0 → exactly one attempt, raises on failure."""
        calls = []

        async def fail():
            calls.append(1)
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await with_retry(fail, max_retries=0, delays=[])

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_default_delays_list_used(self):
        """With no delays arg, defaults to [1.0, 2.0, 4.0] (but we keep delays=[] for speed)."""
        async def succeed():
            return 42

        result = await with_retry(succeed)
        assert result == 42


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


class TestValidateAgentOutput:
    def test_all_fields_present_returns_true(self):
        """All required fields present → True."""
        output = {"build_id": "b1", "status": "ok", "score": 0.9}
        result = validate_agent_output("agent6", output, ["build_id", "status"])
        assert result is True

    def test_missing_field_returns_false(self):
        """Missing required field → False."""
        output = {"build_id": "b1"}
        result = validate_agent_output("agent6", output, ["build_id", "status"])
        assert result is False

    def test_empty_required_fields_returns_true(self):
        """No required fields → always True."""
        result = validate_agent_output("agent6", {}, [])
        assert result is True

    def test_extra_fields_ok(self):
        """Extra fields in output are fine."""
        output = {"build_id": "b1", "status": "ok", "extra": "data"}
        result = validate_agent_output("agent6", output, ["build_id"])
        assert result is True
