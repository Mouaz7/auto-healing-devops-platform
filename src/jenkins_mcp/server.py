"""Agent 1: Pipeline Monitor MCP server — port 8082."""
from __future__ import annotations

import logging
import os

from aiohttp import web

from src.shared.mcp_base import MCPServiceBase
from src.jenkins_mcp.log_fetcher import LogFetcher
from src.jenkins_mcp.webhook_handler import WebhookHandler

logger = logging.getLogger(__name__)

_MOCK_MODE = os.getenv("JENKINS_MOCK_MODE", "true").lower() == "true"


class JenkinsMCPServer(MCPServiceBase):
    """Agent 1 MCP server.

    Endpoints:
        POST /webhook/jenkins     — receive Jenkins build webhook
        POST /tools/fetch_logs    — fetch raw build logs
        GET  /tools/get_build_info — get build metadata
        GET  /health              — health check (inherited)
        GET  /metrics             — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("jenkins_mcp", 8082)
        self.handler = WebhookHandler()
        self.fetcher = LogFetcher(mock_mode=_MOCK_MODE)

    async def setup_routes(self) -> None:
        """Register Jenkins-specific routes on self.app."""
        self.app.router.add_post("/webhook/jenkins",     self.webhook_endpoint)
        self.app.router.add_post("/tools/fetch_logs",    self.fetch_logs_endpoint)
        self.app.router.add_get("/tools/get_build_info", self.get_build_info_endpoint)

    async def webhook_endpoint(self, request: web.Request) -> web.Response:
        """Receive and process a Jenkins webhook payload."""
        try:
            payload = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        event = self.handler.handle(payload)
        if event is None:
            return web.json_response({"status": "ignored"}, status=200)

        return web.json_response({
            "status": "accepted",
            "build_id": event.build_id,
            "repo": event.repo,
            "branch": event.branch,
            "timestamp": event.timestamp.isoformat(),
        })

    async def fetch_logs_endpoint(self, request: web.Request) -> web.Response:
        """Fetch raw build logs for a given job/build."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        job_name = data.get("job_name", "")
        build_id = data.get("build_id", "")
        if not job_name or not build_id:
            return web.json_response(
                {"error": "job_name and build_id required"}, status=400
            )

        try:
            raw_log = await self.fetcher.fetch(job_name, build_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("fetch_logs_failed build_id=%s error=%s", build_id, exc)
            return web.json_response({"error": str(exc)}, status=502)

        return web.json_response({
            "build_id": build_id,
            "log_length": len(raw_log),
            "raw_log": raw_log,
        })

    async def get_build_info_endpoint(self, request: web.Request) -> web.Response:
        """Return metadata for a build that was previously accepted via webhook."""
        build_id = request.query.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)

        if build_id not in self.handler._seen_builds:  # pylint: disable=protected-access
            return web.json_response({"error": "build not found"}, status=404)

        return web.json_response({
            "build_id": build_id,
            "status": "known",
        })


if __name__ == "__main__":
    server = JenkinsMCPServer()
    server.run()
