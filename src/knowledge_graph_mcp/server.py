"""Agent 4: Error Analyst MCP server — port 8084."""
from __future__ import annotations

import logging
import os

from aiohttp import web

from src.shared.mcp_base import MCPServiceBase
from src.knowledge_graph_mcp.failure_analyser import FailureAnalyser, make_analyser

logger = logging.getLogger(__name__)

_MOCK_MODE = os.getenv("KNOWLEDGE_GRAPH_MOCK_MODE", "false").lower() == "true"


class KnowledgeGraphMCPServer(MCPServiceBase):
    """Agent 4 MCP server.

    Endpoints:
        POST /tools/analyze_failure — analyse cleaned build logs
        GET  /health                — health check (inherited)
        GET  /metrics               — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("knowledge_graph_mcp", 8084)
        if _MOCK_MODE:
            self._analyser: FailureAnalyser = FailureAnalyser(nim_client=None)
        else:
            self._analyser = make_analyser()

    async def setup_routes(self) -> None:
        """Register knowledge-graph-specific routes on self.app."""
        self.app.router.add_post("/tools/analyze_failure", self.analyze_endpoint)

    async def analyze_endpoint(self, request: web.Request) -> web.Response:
        """Analyse build failure and return structured FailureAnalysis."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        build_id = data.get("build_id", "")
        cleaned_logs = data.get("cleaned_logs", "")

        if not build_id or not cleaned_logs:
            return web.json_response(
                {"error": "build_id and cleaned_logs are required"}, status=400
            )

        result = self._analyser.analyse(cleaned_logs=cleaned_logs, build_id=build_id)
        logger.info(
            "analyze_failure build_id=%s error_type=%s blast_radius=%s confidence=%.2f",
            build_id, result.error_type.value, result.blast_radius.value, result.confidence,
        )

        return web.json_response({
            "build_id": result.build_id,
            "error_type": result.error_type.value,
            "blast_radius": result.blast_radius.value,
            "affected_files": result.affected_files,
            "confidence": result.confidence,
            "root_cause": result.root_cause,
            "stack_trace": result.stack_trace,
        })


if __name__ == "__main__":
    server = KnowledgeGraphMCPServer()
    server.run()
