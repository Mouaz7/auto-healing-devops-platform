"""Orchestrator MCP server — port 8085.

Sprint 2: state machine skeleton.
Sprint 3: full Agent 1→3→4→5→6 pipeline chain.
Sprint 4: GitHub PR approval — YELLOW creates a PR, webhook advances workflow.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

import httpx
from aiohttp import web

from src.shared.config import SERVICE_URLS
from src.shared.mcp_base import MCPServiceBase
from src.shared.models import WorkflowState, WorkflowStatus
from src.shared.resilience import handle_agent_failure, trigger_global_fallback
from src.orchestrator_mcp.workflow import (
    WorkflowEngine,
    InvalidTransitionError,
    WorkflowNotFoundError,
)
from src.gerrit_mcp.github_approver import extract_build_id

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 60.0   # seconds per agent call
_GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


class OrchestratorMCPServer(MCPServiceBase):
    """Orchestrator MCP server.

    Endpoints:
        POST /tools/handle_build_failure   — run full Agent 1→3→4→5→6 pipeline
        GET  /tools/get_workflow_status    — query workflow status
        POST /webhooks/github              — receive GitHub PR events
        POST /workflows                    — register workflow (REST)
        GET  /workflows/{build_id}         — get workflow state (REST)
        POST /workflows/{build_id}/advance — advance state (REST)
        GET  /workflows/active             — list active workflows (REST)
        GET  /health                       — health check (inherited)
        GET  /metrics                      — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("orchestrator_mcp", 8085)
        self.engine = WorkflowEngine()

    async def setup_routes(self) -> None:
        """Register orchestrator-specific routes on self.app."""
        self.app.router.add_post("/tools/handle_build_failure",   self.handle_build_failure)
        self.app.router.add_get("/tools/get_workflow_status",     self.get_workflow_status)
        self.app.router.add_post("/webhooks/github",              self.github_webhook)
        self.app.router.add_post("/workflows",                    self.create_workflow)
        self.app.router.add_get("/workflows/active",              self.list_active)
        self.app.router.add_get("/workflows/{build_id}",          self.get_workflow)
        self.app.router.add_post("/workflows/{build_id}/advance", self.advance_workflow)

    # ------------------------------------------------------------------
    # Full pipeline — Agent 1→3→4→5→6
    # ------------------------------------------------------------------

    async def handle_build_failure(self, request: web.Request) -> web.Response:
        """Run the full auto-healing pipeline for a build failure.

        Sequence:
          PENDING → ANALYSING  (Agent 3: clean_logs)
                  → ANALYSING  (Agent 4: analyze_failure)
          ANALYSING → GENERATING_FIX (Agent 5: generate_fix)
          GENERATING_FIX → VALIDATING (Agent 6: evaluate_and_notify)
          VALIDATING → COMPLETED | AWAITING_REVIEW (+ GitHub PR) | BLOCKED
        """
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        build_id = data.get("build_id", "")
        raw_log  = data.get("raw_log", "")
        repo     = data.get("repo", "")
        if not build_id or not raw_log:
            return web.json_response(
                {"error": "build_id and raw_log are required"}, status=400
            )

        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                result = await self._run_pipeline(client, build_id, raw_log, repo)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                handle_agent_failure("orchestrator", build_id, str(exc))
                self._safe_fail(build_id, str(exc))
                await trigger_global_fallback("orchestrator", build_id, str(exc))
                return web.json_response(
                    {"build_id": build_id, "status": "FAILED", "error": str(exc)},
                    status=500,
                )

        return web.json_response(result)

    async def _run_pipeline(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        raw_log: str,
        repo: str = "",
    ) -> dict:
        """Execute the full 4-step pipeline and return the final result dict."""
        # Step 1: Agent 3 — clean logs
        self.engine.advance(build_id, WorkflowStatus.ANALYSING)
        clean_resp = await client.post(
            f"{SERVICE_URLS['log_cleaner']}/tools/clean_logs",
            json={"build_id": build_id, "raw_log": raw_log},
        )
        clean_resp.raise_for_status()
        cleaned = clean_resp.json()

        # Step 2: Agent 4 — analyze failure
        analyse_resp = await client.post(
            f"{SERVICE_URLS['knowledge_graph']}/tools/analyze_failure",
            json={"build_id": build_id, "cleaned_logs": cleaned["cleaned_logs"]},
        )
        analyse_resp.raise_for_status()
        analysis = analyse_resp.json()

        # Step 2b: Gerrit MCP — fetch code context for affected files (max 3)
        code_context = ""
        if repo and analysis.get("affected_files"):
            for file_path in analysis["affected_files"][:3]:
                try:
                    ctx_resp = await client.post(
                        f"{SERVICE_URLS['gerrit']}/tools/fetch_file",
                        json={"repo": repo, "file_path": file_path},
                    )
                    if ctx_resp.status_code == 200:
                        code_context += ctx_resp.json().get("content", "")
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # code context is best-effort

        # Step 3: Agent 5 — generate fix
        self.engine.advance(build_id, WorkflowStatus.GENERATING_FIX)
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
                "code_context":   code_context,
            },
        )
        fix_resp.raise_for_status()
        fix = fix_resp.json()

        # Step 4: Agent 6 — traffic light + notify
        self.engine.advance(build_id, WorkflowStatus.VALIDATING)
        notify_resp = await client.post(
            f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify",
            json={
                "build_id":       build_id,
                "fix_patch":      fix["fix_patch"],
                "confidence":     fix["confidence"],
                "explanation":    fix.get("explanation", ""),
                "error_type":     analysis["error_type"],
                "blast_radius":   analysis["blast_radius"],
                "affected_files": analysis["affected_files"],
            },
        )
        notify_resp.raise_for_status()
        verdict = notify_resp.json()

        # Advance to final state based on traffic light
        colour = verdict.get("status", "RED")
        pr_url = ""

        if colour == "GREEN" and verdict.get("auto_merge_allowed"):
            self.engine.advance(build_id, WorkflowStatus.APPLYING_FIX)
            self.engine.advance(build_id, WorkflowStatus.COMPLETED)

        elif colour == "YELLOW":
            self.engine.advance(build_id, WorkflowStatus.AWAITING_REVIEW)
            # Create GitHub PR so the team can approve via GitHub
            if repo:
                pr_url = await self._create_github_pr(
                    client, build_id, repo,
                    fix["fix_patch"], analysis["affected_files"],
                )

        else:
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)

        final_status = self.engine.get(build_id).status.value
        logger.info(
            "pipeline_complete build_id=%s verdict=%s final=%s pr_url=%s",
            build_id, colour, final_status, pr_url,
        )
        return {
            "build_id":    build_id,
            "status":      final_status,
            "colour":      colour,
            "final_score": verdict.get("final_score"),
            "notified":    verdict.get("notified", False),
            "pr_url":      pr_url,
        }

    async def _create_github_pr(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        repo: str,
        patch: str,
        affected_files: list,
    ) -> str:
        """Call gerrit-mcp to open a GitHub PR. Returns the PR URL or empty string."""
        try:
            resp = await client.post(
                f"{SERVICE_URLS['gerrit']}/tools/submit_patch",
                json={
                    "build_id":       build_id,
                    "repo":           repo,
                    "patch":          patch,
                    "affected_files": affected_files,
                },
            )
            resp.raise_for_status()
            pr_url = str(resp.json().get("pr_url", ""))
            logger.info("github_pr_created build_id=%s pr_url=%s", build_id, pr_url)
            return pr_url
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("github_pr_failed build_id=%s error=%s", build_id, exc)
            return ""

    def _safe_fail(self, build_id: str, reason: str) -> None:
        """Mark workflow as FAILED, ignoring errors if already terminal."""
        try:
            self.engine.fail(build_id, reason)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # ------------------------------------------------------------------
    # GitHub webhook — PR approved / merged → advance workflow
    # ------------------------------------------------------------------

    async def github_webhook(self, request: web.Request) -> web.Response:
        """Receive GitHub PR webhooks and advance AWAITING_REVIEW workflows.

        Validates the ``X-Hub-Signature-256`` header when
        ``GITHUB_WEBHOOK_SECRET`` is set.  On a ``pull_request`` event with
        action ``closed`` + ``merged: true``, extracts the build_id from the
        branch name ``auto-heal/{build_id}`` and advances the workflow to
        APPLYING_FIX → COMPLETED.
        """
        body = await request.read()

        if _GITHUB_WEBHOOK_SECRET:
            if not self._verify_github_signature(body, request):
                return web.json_response({"error": "invalid signature"}, status=401)

        try:
            payload = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        event = request.headers.get("X-GitHub-Event", "")
        action = payload.get("action", "")

        if event == "pull_request" and action == "closed":
            merged = payload.get("pull_request", {}).get("merged", False)
            branch = payload.get("pull_request", {}).get("head", {}).get("ref", "")
            build_id = extract_build_id(branch)

            if merged and build_id:
                self._advance_after_approval(build_id)
                logger.info("github_pr_merged build_id=%s branch=%s", build_id, branch)
                return web.json_response(
                    {"build_id": build_id, "status": "COMPLETED", "action": "advanced"}
                )

        if event == "pull_request_review" and action == "submitted":
            state = payload.get("review", {}).get("state", "")
            branch = payload.get("pull_request", {}).get("head", {}).get("ref", "")
            build_id = extract_build_id(branch)

            if state == "approved" and build_id:
                self._advance_after_approval(build_id)
                logger.info(
                    "github_pr_approved build_id=%s branch=%s", build_id, branch
                )
                return web.json_response(
                    {"build_id": build_id, "status": "APPLYING_FIX", "action": "advanced"}
                )

        return web.json_response({"action": "ignored"})

    def _advance_after_approval(self, build_id: str) -> None:
        """Advance AWAITING_REVIEW → APPLYING_FIX → COMPLETED."""
        try:
            state = self.engine.get(build_id)
            if state.status == WorkflowStatus.AWAITING_REVIEW:
                self.engine.advance(build_id, WorkflowStatus.APPLYING_FIX)
                self.engine.advance(build_id, WorkflowStatus.COMPLETED)
        except (WorkflowNotFoundError, InvalidTransitionError) as exc:
            logger.warning(
                "advance_after_approval_failed build_id=%s error=%s", build_id, exc
            )

    @staticmethod
    def _verify_github_signature(body: bytes, request: web.Request) -> bool:
        """Validate HMAC-SHA256 signature from GitHub."""
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not sig_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            _GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    # ------------------------------------------------------------------
    # REST workflow management endpoints
    # ------------------------------------------------------------------

    async def create_workflow(self, request: web.Request) -> web.Response:
        """Register a new workflow."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)
        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        return web.json_response(_serialise(state), status=201)

    async def get_workflow(self, request: web.Request) -> web.Response:
        """Return the current state of a single workflow."""
        build_id = request.match_info["build_id"]
        try:
            state = self.engine.get(build_id)
        except WorkflowNotFoundError:
            return web.json_response({"error": "workflow not found"}, status=404)
        return web.json_response(_serialise(state))

    async def advance_workflow(self, request: web.Request) -> web.Response:
        """Manually advance a workflow to the next status."""
        build_id = request.match_info["build_id"]
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        next_status_str = data.get("next_status", "")
        try:
            next_status = WorkflowStatus(next_status_str)
        except ValueError:
            return web.json_response(
                {"error": f"unknown status '{next_status_str}'"}, status=400
            )
        try:
            state = self.engine.advance(build_id, next_status)
        except WorkflowNotFoundError:
            return web.json_response({"error": "workflow not found"}, status=404)
        except InvalidTransitionError as exc:
            return web.json_response({"error": str(exc)}, status=422)
        return web.json_response(_serialise(state))

    async def list_active(self, _request: web.Request) -> web.Response:
        """Return all active (non-terminal) workflows."""
        return web.json_response([_serialise(s) for s in self.engine.list_active()])

    async def get_workflow_status(self, request: web.Request) -> web.Response:
        """Return current workflow status for a given build_id."""
        build_id = request.query.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)
        try:
            state = self.engine.get(build_id)
        except WorkflowNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"build_id": build_id, "status": state.status.value})


def _serialise(state: WorkflowState) -> dict:
    return {
        "build_id":      state.build_id,
        "status":        state.status.value,
        "retry_count":   state.retry_count,
        "error_message": state.error_message,
        "created_at":    state.created_at.isoformat(),
        "updated_at":    state.updated_at.isoformat(),
    }


if __name__ == "__main__":
    server = OrchestratorMCPServer()
    server.run()
