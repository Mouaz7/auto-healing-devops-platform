"""Scenario router — routes BuildEvents to Scenario A or B pipelines.

Sprint 4 full implementation:
  Scenario A (BUG_FIX_FROM_COMMENT)  — full Agent 3→4→5→6 chain
  Scenario B (AUTONOMOUS_DEVELOPMENT) — Agent 5→6 only (no log cleaning or analysis)
  YELLOW (YELLOW_MANUAL)              — notify team, no automated action

The router delegates HTTP calls to the relevant MCP services via httpx.
It does NOT own workflow state — the WorkflowEngine in OrchestratorMCPServer
is the single source of truth.
"""
from __future__ import annotations

import logging

import httpx

from src.shared.config import SERVICE_URLS
from src.shared.models import BuildEvent, TaskScenario

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 60.0


class ScenarioRouter:
    """Route a BuildEvent to the appropriate agent sub-pipeline."""

    def route(self, event: BuildEvent) -> TaskScenario:
        """Classify *event* into a scenario based on status and job metadata.

        Rules:
          - Status FAILURE + known CI job pattern → Scenario A (bug fix)
          - Feature job name keyword              → Scenario B
          - Anything else                         → YELLOW
        """
        status = (event.status or "").upper()
        job    = (event.job_name or "").lower()

        if status == "FAILURE":
            return TaskScenario.BUG_FIX_FROM_COMMENT

        if any(kw in job for kw in ("feature", "develop", "implement", "new-")):
            return TaskScenario.AUTONOMOUS_DEVELOPMENT

        return TaskScenario.YELLOW_MANUAL

    async def execute_scenario_a(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        raw_log: str,
        repo: str = "",
    ) -> dict:
        """Scenario A: clean logs → analyse → generate fix → notify.

        Full Agent 3→4→5→6 chain.
        """
        logger.info("scenario_a_start build_id=%s", build_id)

        # Agent 3 — clean logs
        clean_resp = await client.post(
            f"{SERVICE_URLS['log_cleaner']}/tools/clean_logs",
            json={"build_id": build_id, "raw_log": raw_log},
        )
        clean_resp.raise_for_status()
        cleaned = clean_resp.json()

        # Agent 4 — analyze failure
        analyse_resp = await client.post(
            f"{SERVICE_URLS['knowledge_graph']}/tools/analyze_failure",
            json={"build_id": build_id, "cleaned_logs": cleaned["cleaned_logs"]},
        )
        analyse_resp.raise_for_status()
        analysis = analyse_resp.json()

        # Agent 5 — generate fix
        fix_resp = await client.post(
            f"{SERVICE_URLS['llm']}/tools/generate_fix",
            json={
                "build_id":       build_id,
                "error_type":     analysis["error_type"],
                "blast_radius":   analysis["blast_radius"],
                "affected_files": analysis["affected_files"],
                "confidence":     analysis["confidence"],
                "root_cause":     analysis["root_cause"],
                "cleaned_logs":   cleaned["cleaned_logs"],
            },
        )
        fix_resp.raise_for_status()
        fix = fix_resp.json()

        result = await self._call_agent6(client, build_id, fix, analysis, repo)
        logger.info("scenario_a_complete build_id=%s status=%s", build_id, result.get("status"))
        return result

    async def execute_scenario_b(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        task_description: str,
        repo: str = "",
    ) -> dict:
        """Scenario B: generate feature code → notify (no log analysis).

        Calls Agent 5 directly with a feature description, then Agent 6.
        """
        logger.info("scenario_b_start build_id=%s", build_id)

        # Agent 5 — generate feature code (no analysis context needed)
        fix_resp = await client.post(
            f"{SERVICE_URLS['llm']}/tools/generate_fix",
            json={
                "build_id":       build_id,
                "error_type":     "UNKNOWN",
                "blast_radius":   "LOW",
                "affected_files": [],
                "confidence":     0.5,
                "root_cause":     task_description,
                "cleaned_logs":   task_description,
            },
        )
        fix_resp.raise_for_status()
        fix = fix_resp.json()

        analysis_stub: dict = {
            "error_type":     "UNKNOWN",
            "blast_radius":   "LOW",
            "affected_files": [],
        }
        result = await self._call_agent6(client, build_id, fix, analysis_stub, repo)
        logger.info("scenario_b_complete build_id=%s status=%s", build_id, result.get("status"))
        return result

    async def notify_yellow(
        self, client: httpx.AsyncClient, build_id: str, reason: str
    ) -> dict:
        """YELLOW: call Agent 6 directly to notify team for manual action."""
        logger.info("scenario_yellow build_id=%s reason=%s", build_id, reason)
        resp = await client.post(
            f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify",
            json={
                "build_id":       build_id,
                "fix_patch":      "",
                "confidence":     0.5,
                "explanation":    reason,
                "error_type":     "UNKNOWN",
                "blast_radius":   "LOW",
                "affected_files": [],
            },
        )
        resp.raise_for_status()
        return dict(resp.json())

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _call_agent6(  # pylint: disable=too-many-positional-arguments
        self,
        client: httpx.AsyncClient,
        build_id: str,
        fix: dict,
        analysis: dict,
        repo: str,
    ) -> dict:
        """Call Agent 6 and optionally create GitHub PR on YELLOW."""
        notify_resp = await client.post(
            f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify",
            json={
                "build_id":       build_id,
                "fix_patch":      fix.get("fix_patch", ""),
                "confidence":     fix.get("confidence", 0.5),
                "explanation":    fix.get("explanation", ""),
                "error_type":     analysis.get("error_type", "UNKNOWN"),
                "blast_radius":   analysis.get("blast_radius", "LOW"),
                "affected_files": analysis.get("affected_files", []),
            },
        )
        notify_resp.raise_for_status()
        verdict = notify_resp.json()

        # Create GitHub PR when YELLOW
        pr_url = ""
        if verdict.get("status") == "YELLOW" and repo:
            try:
                pr_resp = await client.post(
                    f"{SERVICE_URLS['gerrit']}/tools/submit_patch",
                    json={
                        "build_id":       build_id,
                        "repo":           repo,
                        "patch":          fix.get("fix_patch", ""),
                        "affected_files": analysis.get("affected_files", []),
                    },
                )
                pr_url = pr_resp.json().get("pr_url", "")
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("pr_creation_failed build_id=%s", build_id)

        return {**verdict, "pr_url": pr_url}
