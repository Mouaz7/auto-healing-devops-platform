"""Tests for ScenarioRouter HTTP pipeline methods."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.orchestrator_mcp.scenario_router import ScenarioRouter
from src.shared.config import SERVICE_URLS


@pytest.fixture
def router() -> ScenarioRouter:
    return ScenarioRouter()


class TestExecuteScenarioA:
    @respx.mock
    @pytest.mark.asyncio
    async def test_scenario_a_calls_all_agents(self, router):
        """Scenario A calls Agent 3, 4, 5, 6 in order."""
        clean_url = respx.post(f"{SERVICE_URLS['log_cleaner']}/tools/clean_logs").mock(
            return_value=httpx.Response(200, json={
                "cleaned_logs": "ImportError: Foo",
                "reduction_pct": 80.0,
            })
        )
        analyse_url = respx.post(f"{SERVICE_URLS['knowledge_graph']}/tools/analyze_failure").mock(
            return_value=httpx.Response(200, json={
                "error_type": "IMPORT_ERROR",
                "blast_radius": "LOW",
                "affected_files": ["src/app.py"],
                "confidence": 0.9,
                "root_cause": "Missing import",
            })
        )
        fix_url = respx.post(f"{SERVICE_URLS['llm']}/tools/generate_fix").mock(
            return_value=httpx.Response(200, json={
                "fix_patch": "from lib import Foo",
                "confidence": 0.92,
                "explanation": "Added missing import",
                "files_to_modify": ["src/app.py"],
            })
        )
        notify_url = respx.post(f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify").mock(
            return_value=httpx.Response(200, json={
                "status": "GREEN",
                "final_score": 0.95,
                "notified": True,
            })
        )

        async with httpx.AsyncClient(timeout=10) as client:
            result = await router.execute_scenario_a(
                client, "build-a1", "ImportError log", repo=""
            )

        assert clean_url.called
        assert analyse_url.called
        assert fix_url.called
        assert notify_url.called
        assert result["status"] == "GREEN"

    @respx.mock
    @pytest.mark.asyncio
    async def test_scenario_a_agent3_failure_raises(self, router):
        """If Agent 3 returns 500, execute_scenario_a raises HTTPStatusError."""
        respx.post(f"{SERVICE_URLS['log_cleaner']}/tools/clean_logs").mock(
            return_value=httpx.Response(500, json={"error": "crash"})
        )

        async with httpx.AsyncClient(timeout=10) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await router.execute_scenario_a(client, "b-err", "log", repo="")


class TestExecuteScenarioB:
    @respx.mock
    @pytest.mark.asyncio
    async def test_scenario_b_skips_agents_3_and_4(self, router):
        """Scenario B only calls Agent 5 and 6, not 3 or 4."""
        fix_url = respx.post(f"{SERVICE_URLS['llm']}/tools/generate_fix").mock(
            return_value=httpx.Response(200, json={
                "fix_patch": "def new_endpoint(): ...",
                "confidence": 0.8,
                "explanation": "New feature",
                "files_to_modify": ["src/api.py"],
            })
        )
        notify_url = respx.post(f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify").mock(
            return_value=httpx.Response(200, json={
                "status": "YELLOW",
                "final_score": 0.72,
                "notified": True,
            })
        )

        async with httpx.AsyncClient(timeout=10) as client:
            result = await router.execute_scenario_b(
                client, "build-b1", "Add GET /status endpoint", repo=""
            )

        assert fix_url.called
        assert notify_url.called
        assert result["status"] == "YELLOW"

    @respx.mock
    @pytest.mark.asyncio
    async def test_scenario_b_yellow_creates_pr_if_repo(self, router):
        """YELLOW result with repo → attempts to create GitHub PR."""
        respx.post(f"{SERVICE_URLS['llm']}/tools/generate_fix").mock(
            return_value=httpx.Response(200, json={
                "fix_patch": "code",
                "confidence": 0.7,
                "explanation": "feature",
            })
        )
        respx.post(f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify").mock(
            return_value=httpx.Response(200, json={"status": "YELLOW"})
        )
        pr_url_route = respx.post(f"{SERVICE_URLS['gerrit']}/tools/submit_patch").mock(
            return_value=httpx.Response(200, json={"pr_url": "https://github.com/example/pr/1"})
        )

        async with httpx.AsyncClient(timeout=10) as client:
            result = await router.execute_scenario_b(
                client, "build-b2", "feature", repo="example/repo"
            )

        assert pr_url_route.called
        assert result["pr_url"] == "https://github.com/example/pr/1"


class TestNotifyYellow:
    @respx.mock
    @pytest.mark.asyncio
    async def test_notify_yellow_calls_agent6(self, router):
        """notify_yellow sends payload to Agent 6."""
        notify_url = respx.post(f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify").mock(
            return_value=httpx.Response(200, json={"status": "YELLOW", "notified": True})
        )

        async with httpx.AsyncClient(timeout=10) as client:
            result = await router.notify_yellow(client, "build-y1", "ambiguous task")

        assert notify_url.called
        assert result["status"] == "YELLOW"
