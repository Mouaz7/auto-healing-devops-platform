"""Gerrit/GitHub MCP server — port 8083.

Endpoints:
    POST /tools/fetch_file      — fetch source file from local/GitHub/Gerrit
    POST /tools/submit_patch    — create GitHub PR with a fix
    POST /tools/check_approval  — check if a PR is approved or merged
    GET  /health                — health check (inherited)
    GET  /metrics               — Prometheus metrics (inherited)
"""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from src.shared.mcp_base import MCPServiceBase
from src.gerrit_mcp.code_fetcher import CodeFetcher
from src.gerrit_mcp.patch_submitter import PatchSubmitter
from src.gerrit_mcp.github_approver import check_pr_approved, check_pr_merged

logger = logging.getLogger(__name__)


class GerritMCPServer(MCPServiceBase):
    """MCP server wrapping GitHub / Gerrit code operations."""

    def __init__(self) -> None:
        super().__init__("gerrit_mcp", 8083)
        self._fetcher = CodeFetcher(mode="github")
        self._submitter = PatchSubmitter()

    async def setup_routes(self) -> None:
        """Register Gerrit-specific routes on self.app."""
        self.app.router.add_post("/tools/fetch_file",     self.fetch_file_endpoint)
        self.app.router.add_post("/tools/submit_patch",   self.submit_patch_endpoint)
        self.app.router.add_post("/tools/check_approval", self.check_approval_endpoint)

    async def fetch_file_endpoint(self, request: web.Request) -> web.Response:
        """Fetch a file from the configured source backend."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        repo      = data.get("repo", "")
        file_path = data.get("file_path", "")
        ref       = data.get("ref", "main")

        if not file_path:
            return web.json_response({"error": "file_path required"}, status=400)

        try:
            content = await self._fetcher.fetch_file(repo, file_path, ref)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": str(exc)}, status=502)

        return web.json_response({"content": content, "file_path": file_path})

    async def submit_patch_endpoint(self, request: web.Request) -> web.Response:
        """Create a GitHub PR for an auto-generated fix."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        build_id = data.get("build_id", "")
        repo     = data.get("repo", "")
        if not build_id or not repo:
            return web.json_response(
                {"error": "build_id and repo are required"}, status=400
            )

        report_data = {
            k: data[k] for k in (
                "colour", "confidence", "elapsed_s",
                "error_type", "blast_radius", "root_cause", "explanation",
                "bugs_found", "bug_count", "verdict_reason", "final_score",
                "changed_lines", "scan_findings", "parse_error",
                "all_affected_files", "fix_strategy", "bug_list",
                "attempts", "model_used", "bandit_issues", "regression_risk",
                "test_hints", "complexity", "original_code", "cleaned_logs",
            ) if k in data
        } or None

        try:
            result = await self._submitter.create_pr(
                repo=repo,
                build_id=build_id,
                patch=data.get("patch", ""),
                affected_files=data.get("affected_files", []),
                title=data.get("title", ""),
                base_branch=data.get("base_branch", "main"),
                report_data=report_data,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("submit_patch_failed build_id=%s error=%s", build_id, exc)
            return web.json_response({"error": str(exc)}, status=502)

        return web.json_response(result)

    async def check_approval_endpoint(self, request: web.Request) -> web.Response:
        """Check if a GitHub PR is approved or merged."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        repo      = data.get("repo", "")
        pr_number = data.get("pr_number", 0)
        if not repo or not pr_number:
            return web.json_response(
                {"error": "repo and pr_number are required"}, status=400
            )

        merged, approved = await asyncio.gather(
            check_pr_merged(repo, pr_number),
            check_pr_approved(repo, pr_number),
        )
        return web.json_response({
            "repo":      repo,
            "pr_number": pr_number,
            "merged":    merged,
            "approved":  approved,
            "can_apply": merged or approved,
        })


if __name__ == "__main__":
    server = GerritMCPServer()
    server.run()
