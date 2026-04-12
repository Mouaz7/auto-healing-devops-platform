"""Integration test — global fallback: agent failure → RED → Agent 6 notified.

Tests that when any agent in the pipeline raises an exception,
the system correctly:
  1. Calls handle_agent_failure (logs + returns RED payload)
  2. Marks the workflow as FAILED
  3. Calls trigger_global_fallback (notifies Agent 6 with RED)

HTTP calls to Agent 6 are mocked via respx.
"""
from __future__ import annotations

import pytest
import respx
import httpx

from src.shared.resilience import handle_agent_failure, trigger_global_fallback
from src.orchestrator_mcp.workflow import WorkflowEngine
from src.shared.models import WorkflowState, WorkflowStatus


# ---------------------------------------------------------------------------
# handle_agent_failure — pure function, no I/O
# ---------------------------------------------------------------------------

class TestHandleAgentFailure:
    def test_returns_red_payload(self):
        result = handle_agent_failure("log_cleaner", "build-99", "timeout")
        assert result["status"] == "RED"
        assert result["build_id"] == "build-99"
        assert result["failed_agent"] == "log_cleaner"

    def test_reason_included_in_message(self):
        result = handle_agent_failure("llm", "b1", "connection refused")
        assert "connection refused" in result["message"]

    def test_confidence_zero(self):
        result = handle_agent_failure("orchestrator", "b1", "crash")
        assert result["confidence"] == 0.0

    def test_blast_radius_high(self):
        result = handle_agent_failure("knowledge_graph", "b1", "error")
        assert result["blast_radius"] == "HIGH"

    def test_timestamp_present(self):
        result = handle_agent_failure("notification", "b1", "err")
        assert "timestamp" in result
        assert result["timestamp"]


# ---------------------------------------------------------------------------
# trigger_global_fallback — calls Agent 6 via HTTP
# ---------------------------------------------------------------------------

class TestTriggerGlobalFallback:
    @respx.mock
    @pytest.mark.asyncio
    async def test_posts_to_agent6(self):
        route = respx.post("http://localhost:8087/tools/evaluate_and_notify").mock(
            return_value=httpx.Response(200, json={"status": "RED"})
        )
        await trigger_global_fallback("log_cleaner", "build-fallback", "timeout")
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_agent6_unreachable_does_not_raise(self):
        respx.post("http://localhost:8087/tools/evaluate_and_notify").mock(
            side_effect=httpx.ConnectError("refused")
        )
        # Should log and continue — no exception propagated
        await trigger_global_fallback("llm", "build-down", "refused")

    @respx.mock
    @pytest.mark.asyncio
    async def test_payload_contains_build_id(self):
        captured = []

        async def capture(request, route):
            import json
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={})

        respx.post("http://localhost:8087/tools/evaluate_and_notify").mock(
            side_effect=capture
        )
        await trigger_global_fallback("agent4", "build-xyz", "crash")
        assert captured[0]["build_id"] == "build-xyz"


# ---------------------------------------------------------------------------
# Workflow state — failure marking
# ---------------------------------------------------------------------------

class TestWorkflowFailurePath:
    def test_failed_status_is_terminal(self):
        engine = WorkflowEngine()
        state = WorkflowState(build_id="fail-001", status=WorkflowStatus.PENDING)
        engine.register(state)
        engine.advance("fail-001", WorkflowStatus.ANALYSING)
        engine.fail("fail-001", "agent crashed")

        result = engine.get("fail-001")
        assert result.status == WorkflowStatus.FAILED
        assert "agent crashed" in result.error_message

    def test_failed_workflow_not_in_active_list(self):
        engine = WorkflowEngine()
        state = WorkflowState(build_id="fail-002", status=WorkflowStatus.PENDING)
        engine.register(state)
        engine.fail("fail-002", "error")

        active = engine.list_active()
        assert not any(w.build_id == "fail-002" for w in active)

    def test_blocked_workflow_not_in_active_list(self):
        engine = WorkflowEngine()
        state = WorkflowState(build_id="block-001", status=WorkflowStatus.PENDING)
        engine.register(state)
        for step in [
            WorkflowStatus.ANALYSING,
            WorkflowStatus.GENERATING_FIX,
            WorkflowStatus.VALIDATING,
            WorkflowStatus.BLOCKED,
        ]:
            engine.advance("block-001", step)

        active = engine.list_active()
        assert not any(w.build_id == "block-001" for w in active)
