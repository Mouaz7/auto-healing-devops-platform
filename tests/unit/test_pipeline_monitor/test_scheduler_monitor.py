"""Tests for ScheduledMonitor — poll, classify, route."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.scheduler.monitor import ScheduledMonitor
from src.scheduler.task_classifier import TaskClassifier
from src.shared.config import SERVICE_URLS


@pytest.fixture
def classifier() -> TaskClassifier:
    return TaskClassifier(nim_client=None)


@pytest.fixture
def monitor(classifier) -> ScheduledMonitor:
    return ScheduledMonitor(interval_minutes=15, classifier=classifier)


class TestFetchOpenTasks:
    @pytest.mark.asyncio
    async def test_returns_empty_without_github_token(self, monitor, monkeypatch):
        """No GITHUB_TOKEN → empty list returned (graceful degradation)."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        tasks = await monitor._fetch_open_tasks()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_returns_empty_without_repo(self, monitor, monkeypatch):
        """GITHUB_TOKEN set but no GITHUB_REPO → empty list."""
        monkeypatch.setenv("GITHUB_TOKEN", "token123")
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        tasks = await monitor._fetch_open_tasks()
        assert tasks == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetches_issues_from_github(self, monitor, monkeypatch):
        """With token + repo, fetches issues from GitHub API."""
        monkeypatch.setenv("GITHUB_TOKEN", "token123")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")

        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=[
                {"number": 42, "title": "ImportError in CI", "body": "build failed"},
                {"number": 43, "title": "Add dark mode", "body": "feature request"},
            ])
        )

        # Reload monitor to pick up new env vars
        from src.scheduler import monitor as monitor_module
        import importlib
        importlib.reload(monitor_module)
        fresh_monitor = monitor_module.ScheduledMonitor(
            interval_minutes=15, classifier=classifier
        )

        tasks = await fresh_monitor._fetch_open_tasks()
        assert len(tasks) == 2
        assert tasks[0]["title"] == "ImportError in CI"
        assert tasks[1]["id"] == "43"

    @respx.mock
    @pytest.mark.asyncio
    async def test_github_error_returns_empty(self, monitor, monkeypatch):
        """GitHub API error → empty list (graceful degradation)."""
        monkeypatch.setenv("GITHUB_TOKEN", "token123")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")

        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(500)
        )

        from src.scheduler import monitor as monitor_module
        import importlib
        importlib.reload(monitor_module)
        fresh_monitor = monitor_module.ScheduledMonitor(
            interval_minutes=15, classifier=classifier
        )
        tasks = await fresh_monitor._fetch_open_tasks()
        assert tasks == []


class TestRouteTask:
    @respx.mock
    @pytest.mark.asyncio
    async def test_bug_task_sent_to_orchestrator(self, monitor):
        """Bug task (Scenario A) posted to orchestrator."""
        orch_url = respx.post(
            f"{SERVICE_URLS['orchestrator']}/tools/handle_build_failure"
        ).mock(return_value=httpx.Response(200, json={"status": "COMPLETED"}))

        await monitor._route_task({
            "id": "issue-1",
            "title": "ImportError in CI build",
            "description": "ImportError: cannot import Foo",
            "comments": [],
            "repo": "owner/repo",
        })
        assert orch_url.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_yellow_task_sent_to_agent6(self, monitor):
        """YELLOW (ambiguous) task notifies Agent 6."""
        notify_url = respx.post(
            f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify"
        ).mock(return_value=httpx.Response(200, json={"status": "YELLOW"}))

        await monitor._route_task({
            "id": "issue-2",
            "title": "Something happened",
            "description": "Please check this out",
            "comments": [],
            "repo": "",
        })
        assert notify_url.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_feature_task_sent_to_orchestrator(self, monitor):
        """Feature task (Scenario B) posted to orchestrator."""
        orch_url = respx.post(
            f"{SERVICE_URLS['orchestrator']}/tools/handle_build_failure"
        ).mock(return_value=httpx.Response(200, json={"status": "COMPLETED"}))

        await monitor._route_task({
            "id": "issue-3",
            "title": "Add dark mode toggle",
            "description": "Implement dark/light theme switcher",
            "comments": [],
            "repo": "owner/repo",
        })
        assert orch_url.called


class TestPollAndProcess:
    @respx.mock
    @pytest.mark.asyncio
    async def test_processes_all_tasks(self, monitor, monkeypatch):
        """_poll_and_process routes all fetched tasks."""
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")

        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=[
                {"number": 1, "title": "ImportError failure", "body": "error"},
            ])
        )
        orch_url = respx.post(
            f"{SERVICE_URLS['orchestrator']}/tools/handle_build_failure"
        ).mock(return_value=httpx.Response(200, json={}))

        from src.scheduler import monitor as monitor_module
        import importlib
        importlib.reload(monitor_module)
        fresh_monitor = monitor_module.ScheduledMonitor(
            interval_minutes=15, classifier=monitor._classifier
        )
        await fresh_monitor._poll_and_process()
        assert orch_url.called
