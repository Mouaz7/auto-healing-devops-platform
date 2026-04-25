"""Agent 6: Review & Notify MCP server — port 8087."""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from src.shared.mcp_base import MCPServiceBase
from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis
from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
from src.notification_mcp.teams_notifier import send_teams_notification
from src.notification_mcp.slack_notifier import send_slack_notification

logger = logging.getLogger(__name__)


class NotificationMCPServer(MCPServiceBase):
    """Agent 6 MCP server.

    Endpoints:
        POST /tools/evaluate_and_notify — traffic light + Teams/Slack notify
        GET  /health                    — health check (inherited)
        GET  /metrics                   — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("notification_mcp", 8087)

    async def setup_routes(self) -> None:
        """Register notification-service-specific routes on self.app."""
        self.app.router.add_post(
            "/tools/evaluate_and_notify", self.evaluate_and_notify
        )

    async def evaluate_and_notify(self, request: web.Request) -> web.Response:
        """Evaluate fix quality, apply traffic light, and send notifications."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)

        try:
            blast_radius = BlastRadius(data.get("blast_radius", "LOW"))
            error_type   = ErrorType(data.get("error_type", "UNKNOWN"))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        code_fix = CodeFix(
            build_id=build_id,
            fix_patch=data.get("fix_patch", ""),
            confidence=float(data.get("confidence", 0.5)),
            explanation=data.get("explanation", ""),
            files_to_modify=data.get("affected_files", []),
        )
        analysis = FailureAnalysis(
            build_id=build_id,
            error_type=error_type,
            blast_radius=blast_radius,
            affected_files=data.get("affected_files", []),
        )

        result = evaluate_traffic_light(code_fix, analysis)
        files_str = ", ".join(analysis.affected_files) if analysis.affected_files else "(none reported)"
        logger.info(
            "notify_files build_id=%s files=%s files_str=%r",
            build_id, analysis.affected_files, files_str,
        )

        # Fire notifications concurrently — failure does not block the response
        teams_ok, slack_ok = await asyncio.gather(
            send_teams_notification(
                result.colour.value, build_id, result.final_score,
                result.reason, files_str, code_fix.explanation,
            ),
            send_slack_notification(
                result.colour.value, build_id, result.final_score,
                result.reason, files_str, code_fix.explanation,
            ),
        )

        logger.info(
            "evaluate_and_notify build_id=%s colour=%s score=%.3f teams=%s slack=%s",
            build_id, result.colour.value, result.final_score, teams_ok, slack_ok,
        )

        return web.json_response({
            "build_id":          result.build_id,
            "status":            result.colour.value,
            "final_score":       result.final_score,
            "auto_merge_allowed": result.auto_merge_allowed,
            "reason":            result.reason,
            "safety_override":   result.safety_override,
            "notified":          teams_ok or slack_ok,
        })


if __name__ == "__main__":
    server = NotificationMCPServer()
    server.run()
