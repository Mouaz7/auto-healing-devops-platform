"""Agent 5: Code Repairer MCP server — port 8086."""
from __future__ import annotations

import logging
import os

from aiohttp import web

from src.shared.mcp_base import MCPServiceBase
from src.shared.models import BlastRadius, ErrorType, FailureAnalysis
from src.llm_mcp.fix_generator import FixGenerator, make_fix_generator

logger = logging.getLogger(__name__)

_MOCK_MODE = os.getenv("LLM_MOCK_MODE", "false").lower() == "true"


class LLMMCPServer(MCPServiceBase):
    """Agent 5 MCP server.

    Endpoints:
        POST /tools/generate_fix — generate a code fix for a build failure
        GET  /health             — health check (inherited)
        GET  /metrics            — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("llm_mcp", 8086)
        if _MOCK_MODE:
            self._generator: FixGenerator = FixGenerator(nim_client=None)
        else:
            self._generator = make_fix_generator()

    async def setup_routes(self) -> None:
        """Register LLM-service-specific routes on self.app."""
        self.app.router.add_post("/tools/generate_fix", self.generate_fix_endpoint)

    async def generate_fix_endpoint(self, request: web.Request) -> web.Response:
        """Generate a code fix and return it with quality-check metadata."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)

        try:
            error_type = ErrorType(data.get("error_type", "UNKNOWN"))
            blast_radius = BlastRadius(data.get("blast_radius", "LOW"))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        analysis = FailureAnalysis(
            build_id=build_id,
            error_type=error_type,
            blast_radius=blast_radius,
            affected_files=data.get("affected_files", []),
            confidence=data.get("confidence", 0.5),
            root_cause=data.get("root_cause", ""),
        )

        try:
            fix = self._generator.generate_fix(
                analysis=analysis,
                code_context=data.get("code_context", ""),
                cleaned_logs=data.get("cleaned_logs", ""),
            )
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)
        except ValueError as exc:
            # NoCodeContextError, FixTooLongError, SecretLeakError — all caller errors.
            # 422 signals "orchestrator should mark build as BLOCKED for human review".
            return web.json_response(
                {"error": str(exc), "reason": type(exc).__name__}, status=422,
            )

        return web.json_response({
            "build_id":        fix.build_id,
            "fix_patch":       fix.fix_patch,
            "files_to_modify": fix.files_to_modify,
            "confidence":      fix.confidence,
            "explanation":     fix.explanation,
            "lint_ok":         fix.lint_ok,
            "test_ok":         fix.test_ok,
            "changed_lines":   fix.changed_lines,
            "bugs_found":      fix.bugs_found,
        })


if __name__ == "__main__":
    server = LLMMCPServer()
    server.run()
