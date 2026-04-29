"""Orchestrator MCP server — port 8085.

Thin shell composing all functionality from focused mixins:

  - PipelineMixin     — handle_build_failure + Agent 3→4→5→6 pipeline
  - GitHubMixin       — PR creation, auto-merge, GitHub webhook
  - SlackMixin        — Slack interactive Approve/Reject buttons
  - WorkflowApiMixin  — REST CRUD for workflows
  - AdminMixin        — stats, retry, AI code review

Endpoints:
    POST /tools/handle_build_failure     — full Agent 1→3→4→5→6 pipeline
    GET  /tools/get_workflow_status      — query workflow status
    POST /tools/retry_build              — re-queue a failed build
    POST /tools/review_code              — AI code review (no crash needed)
    POST /webhooks/github                — GitHub PR events
    POST /webhooks/slack                 — Slack interactive payloads
    POST /webhooks/slack/commands        — Slack slash commands
    POST /workflows                      — register workflow (REST)
    GET  /workflows/{build_id}           — get workflow state
    POST /workflows/{build_id}/advance   — advance state
    GET  /workflows/active               — list active workflows
    GET  /api/stats                      — system stats
    GET  /health, /metrics               — inherited
"""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

import os

from src.shared.config import SERVICE_URLS  # re-export: tests patch via this module
from src.shared.mcp_base import MCPServiceBase

# Re-exported here (rather than in github_mixin) because tests patch this name
# on the server module: patch("src.orchestrator_mcp.server._GITHUB_WEBHOOK_SECRET").
# github_mixin reads it lazily to avoid a circular import.
_GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

_ = SERVICE_URLS  # keep import alive for test patching
from src.notification_mcp.slack_slash_handler import handle_slash_command
from src.orchestrator_mcp.admin_mixin import AdminMixin
from src.orchestrator_mcp.github_mixin import GitHubMixin
from src.orchestrator_mcp.pipeline_mixin import PipelineMixin
from src.orchestrator_mcp.slack_mixin import SlackMixin
from src.orchestrator_mcp.workflow import WorkflowEngine
from src.orchestrator_mcp.workflow_api_mixin import WorkflowApiMixin

logger = logging.getLogger(__name__)

_PRUNE_INTERVAL = 3600  # how often the background pruner runs (seconds)


class OrchestratorMCPServer(
    PipelineMixin,
    GitHubMixin,
    SlackMixin,
    WorkflowApiMixin,
    AdminMixin,
    MCPServiceBase,
):
    """Composes all orchestrator behaviour from focused mixins."""

    def __init__(self) -> None:
        super().__init__("orchestrator_mcp", 8085)
        self._port = 8085
        self.engine = WorkflowEngine()
        self._prune_task: asyncio.Task | None = None

    async def setup_routes(self) -> None:
        r = self.app.router
        r.add_post("/tools/handle_build_failure",   self.handle_build_failure)
        r.add_get ("/tools/get_workflow_status",    self.get_workflow_status)
        r.add_post("/tools/retry_build",            self.retry_build)
        r.add_post("/tools/review_code",            self.review_code)
        r.add_post("/webhooks/github",              self.github_webhook)
        r.add_post("/webhooks/slack",               self.slack_webhook)
        r.add_post("/webhooks/slack/commands",      handle_slash_command)
        r.add_post("/workflows",                    self.create_workflow)
        r.add_get ("/workflows/active",             self.list_active)
        r.add_get ("/workflows/{build_id}",         self.get_workflow)
        r.add_post("/workflows/{build_id}/advance", self.advance_workflow)
        r.add_get ("/api/stats",                    self.get_stats)
        self.app.on_startup.append(self._start_pruner)
        self.app.on_cleanup.append(self._stop_pruner)

    async def _start_pruner(self, _app: web.Application) -> None:
        self._prune_task = asyncio.create_task(self._prune_loop())

    async def _stop_pruner(self, _app: web.Application) -> None:
        if self._prune_task:
            self._prune_task.cancel()
            try:
                await self._prune_task
            except asyncio.CancelledError:
                pass

    async def _prune_loop(self) -> None:
        """Background task: prune stale workflows every hour."""
        while True:
            await asyncio.sleep(_PRUNE_INTERVAL)
            try:
                result = self.engine.prune_stale()
                logger.info("prune_loop result=%s", result)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("prune_loop_error error=%s", exc)


if __name__ == "__main__":
    server = OrchestratorMCPServer()
    server.run()
