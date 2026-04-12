"""Scheduled monitor — polls GitHub Issues / Jira, classifies via Agent 2, routes.

Runs every ``interval_minutes`` (default 15). For each open task:
  1. Classify with TaskClassifier (Agent 2)
  2. Route to orchestrator:
       A → handle_build_failure (full Agent 3→4→5→6 pipeline)
       B → handle_build_failure with scenario=B hint (Agent 5→6 only)
       YELLOW → notify team via Agent 6 that manual classification is needed
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from src.scheduler.task_classifier import TaskClassifier, make_classifier
from src.shared.config import SERVICE_URLS
from src.shared.models import TaskScenario

logger = logging.getLogger(__name__)

_SCHEDULE_INTERVAL_MINUTES = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "15"))
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_GITHUB_API = "https://api.github.com"


class ScheduledMonitor:
    """Poll open tasks and route them through the agent pipeline.

    Args:
        interval_minutes: How often to poll (default from env or 15 min).
        classifier: Optional pre-built TaskClassifier (for testing).
    """

    def __init__(
        self,
        interval_minutes: int = _SCHEDULE_INTERVAL_MINUTES,
        classifier: TaskClassifier | None = None,
    ) -> None:
        self.interval = interval_minutes * 60
        self._classifier = classifier or make_classifier()

    async def run(self) -> None:
        """Main loop — poll and process until cancelled."""
        logger.info("scheduler_started interval_minutes=%d", self.interval // 60)
        while True:
            try:
                await self._poll_and_process()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("scheduler_poll_error — continuing")
            await asyncio.sleep(self.interval)

    async def _poll_and_process(self) -> None:
        """Fetch open tasks and route each one."""
        tasks = await self._fetch_open_tasks()
        logger.info("scheduler_poll found=%d tasks", len(tasks))
        for task in tasks:
            await self._route_task(task)

    async def _fetch_open_tasks(self) -> list[dict]:
        """Fetch open GitHub Issues labelled ``auto-heal``.

        Returns an empty list when ``GITHUB_TOKEN`` is not set or the
        ``GITHUB_REPO`` env var is missing (graceful degradation).
        """
        repo = os.getenv("GITHUB_REPO", "")
        if not repo or not _GITHUB_TOKEN:
            logger.debug("fetch_open_tasks skipped — GITHUB_TOKEN or GITHUB_REPO not set")
            return []

        url = f"{_GITHUB_API}/repos/{repo}/issues"
        headers = {
            "Authorization": f"token {_GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        params = {"state": "open", "labels": "auto-heal", "per_page": "50"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                issues = resp.json()
                return [
                    {
                        "id":          str(issue["number"]),
                        "title":       issue.get("title", ""),
                        "description": issue.get("body", "") or "",
                        "comments":    [],
                        "repo":        repo,
                    }
                    for issue in issues
                ]
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("fetch_open_tasks_failed error=%s", exc)
            return []

    async def _route_task(self, task: dict) -> None:
        """Classify a task and POST it to the orchestrator."""
        scenario = self._classifier.classify(
            title=task.get("title", ""),
            description=task.get("description", ""),
            comments=task.get("comments", []),
        )
        task_id = task.get("id", "unknown")
        logger.info("task_classified id=%s scenario=%s", task_id, scenario.value)

        async with httpx.AsyncClient(timeout=30) as client:
            if scenario == TaskScenario.YELLOW_MANUAL:
                await self._notify_yellow(client, task_id, task)
            else:
                await self._send_to_orchestrator(client, task_id, task, scenario)

    async def _send_to_orchestrator(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        task: dict,
        scenario: TaskScenario,
    ) -> None:
        """POST task to orchestrator handle_build_failure."""
        payload = {
            "build_id":  task_id,
            "raw_log":   f"{task.get('title', '')} — {task.get('description', '')}",
            "repo":      task.get("repo", ""),
            "scenario":  scenario.value,
        }
        try:
            resp = await client.post(
                f"{SERVICE_URLS['orchestrator']}/tools/handle_build_failure",
                json=payload,
            )
            logger.info(
                "orchestrator_routed id=%s scenario=%s status=%d",
                task_id, scenario.value, resp.status_code,
            )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.error("orchestrator_route_failed id=%s error=%s", task_id, exc)

    async def _notify_yellow(
        self, client: httpx.AsyncClient, task_id: str, task: dict
    ) -> None:
        """Call Agent 6 directly to notify that manual classification is needed."""
        payload = {
            "build_id":   task_id,
            "fix_patch":  "",
            "confidence": 0.5,
            "explanation": (
                f"Task '{task.get('title', '')}' could not be auto-classified. "
                "Manual review required."
            ),
            "error_type":   "UNKNOWN",
            "blast_radius": "LOW",
            "affected_files": [],
        }
        try:
            await client.post(
                f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify",
                json=payload,
            )
            logger.info("yellow_notified id=%s", task_id)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("yellow_notify_failed id=%s error=%s", task_id, exc)


if __name__ == "__main__":
    monitor = ScheduledMonitor()
    asyncio.run(monitor.run())
