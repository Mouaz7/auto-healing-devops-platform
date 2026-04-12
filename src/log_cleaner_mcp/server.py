"""Agent 3: Log Analyst MCP server — port 8081."""
from __future__ import annotations

import logging
import os

from aiohttp import web

from src.shared.mcp_base import MCPServiceBase
from src.log_cleaner_mcp.pipeline import LogCleaningPipeline, make_pipeline

logger = logging.getLogger(__name__)

_MOCK_MODE = os.getenv("LOG_CLEANER_MOCK_MODE", "false").lower() == "true"


class LogCleanerMCPServer(MCPServiceBase):
    """Agent 3 MCP server.

    Endpoints:
        POST /tools/clean_logs — clean a raw build log
        GET  /health           — health check (inherited)
        GET  /metrics          — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("log_cleaner_mcp", 8081)
        if _MOCK_MODE:
            self._pipeline: LogCleaningPipeline = LogCleaningPipeline(nim_client=None)
        else:
            self._pipeline = make_pipeline()

    async def setup_routes(self) -> None:
        """Register log-cleaner-specific routes on self.app."""
        self.app.router.add_post("/tools/clean_logs", self.clean_log_endpoint)

    async def clean_log_endpoint(self, request: web.Request) -> web.Response:
        """Clean a raw Jenkins build log and return the result."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        raw_log = data.get("raw_log", "")
        build_id = data.get("build_id", "")

        if not raw_log:
            return web.json_response({"error": "raw_log is required"}, status=400)

        result = self._pipeline.clean(raw_log)
        logger.info(
            "clean_log build_id=%s original=%d cleaned=%d ratio=%.2f llm=%s",
            build_id, result.original_lines, result.cleaned_lines,
            result.reduction_ratio, result.used_llm,
        )

        return web.json_response({
            "build_id": build_id,
            "cleaned_logs": result.cleaned_text,
            "reduction_pct": round(result.reduction_ratio * 100, 1),
            "original_length": len(raw_log),
            "cleaned_length": len(result.cleaned_text),
            "original_lines": result.original_lines,
            "cleaned_lines": result.cleaned_lines,
            "used_llm": result.used_llm,
        })


if __name__ == "__main__":
    server = LogCleanerMCPServer()
    server.run()
