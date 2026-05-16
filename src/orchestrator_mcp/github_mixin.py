"""GitHubMixin — PR creation, merge, and webhook handling."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

import httpx
from aiohttp import web

from src.shared import config as _config
from src.shared.models import WorkflowStatus
from src.gerrit_mcp.github_approver import extract_build_id
from src.orchestrator_mcp.workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)


def _webhook_secret() -> str:
    """Read GITHUB_WEBHOOK_SECRET lazily from the server module so tests can
    patch `src.orchestrator_mcp.server._GITHUB_WEBHOOK_SECRET` at runtime.
    Lazy lookup avoids a circular import.
    """
    from src.orchestrator_mcp import server  # pylint: disable=import-outside-toplevel
    return server._GITHUB_WEBHOOK_SECRET  # pylint: disable=protected-access


def _pr_title(build_id: str, colour: str) -> str:
    if colour == "GREEN":
        return f"[auto-heal][GREEN] Auto-fix build {build_id}"
    return f"[auto-heal][YELLOW] Human review required — build {build_id}"


async def _submit_patch(
    client: httpx.AsyncClient,
    build_id: str,
    repo: str,
    patch: str,
    affected_files: list,
    auto_merge: bool,
    report_data: dict | None = None,
) -> dict:
    """Single source of truth for calling gerrit-mcp /tools/submit_patch."""
    colour = (report_data or {}).get("colour", "YELLOW")
    payload: dict = {
        "build_id":       build_id,
        "repo":           repo,
        "patch":          patch,
        "affected_files": affected_files,
        "title":          _pr_title(build_id, colour),
    }
    if report_data:
        payload.update(report_data)
    resp = await client.post(
        f"{_config.SERVICE_URLS['gerrit']}/tools/submit_patch",
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


class GitHubMixin:
    """PR creation, auto-merge, and GitHub webhook handler."""

    async def _create_github_pr(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        repo: str,
        patch: str,
        affected_files: list,
        auto_merge: bool = False,
        report_data: dict | None = None,
    ) -> str:
        """Open a PR via gerrit-mcp. Auto-merge is disabled — every PR requires
        a human review to enforce the Human-in-the-Loop control mechanism.
        Returns the PR URL."""
        try:
            pr_data = await _submit_patch(
                client, build_id, repo, patch, affected_files, auto_merge,
                report_data=report_data,
            )
            pr_url = str(pr_data.get("pr_url", ""))
            pr_number = pr_data.get("pr_number", 0)
            logger.info(
                "github_pr_created build_id=%s pr_url=%s auto_merge=%s",
                build_id, pr_url, auto_merge,
            )
            # Enforce Human-in-the-Loop: every PR must be reviewed by a human
            # before merging, regardless of the AI confidence score.
            # if auto_merge and pr_number:
            #     await self._merge_pr(client, repo, pr_number)
            return pr_url
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("github_pr_failed build_id=%s error=%s", build_id, exc)
            return ""

    async def _create_github_pr_with_number(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        repo: str,
        patch: str,
        affected_files: list,
        auto_merge: bool = False,
        report_data: dict | None = None,
    ) -> dict:
        """Like _create_github_pr but returns full {pr_url, pr_number, branch}."""
        try:
            return await _submit_patch(
                client, build_id, repo, patch, affected_files, auto_merge,
                report_data=report_data,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("github_pr_failed build_id=%s error=%s", build_id, exc)
            return {"pr_url": "", "pr_number": 0, "branch": ""}

    async def _merge_pr(
        self, client: httpx.AsyncClient, repo: str, pr_number: int,
    ) -> None:
        """Merge a GitHub PR automatically (GREEN path)."""
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            return
        try:
            resp = await client.put(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
                headers={
                    "Authorization": f"token {token}",
                    "Accept":        "application/vnd.github+json",
                },
                json={"merge_method": "squash"},
            )
            if resp.status_code == 200:
                logger.info("pr_auto_merged repo=%s pr=%d", repo, pr_number)
            else:
                logger.warning("pr_merge_failed repo=%s pr=%d status=%d",
                               repo, pr_number, resp.status_code)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("pr_merge_error repo=%s pr=%d error=%s",
                           repo, pr_number, exc)

    # --- Webhook ------------------------------------------------------

    async def github_webhook(self, request: web.Request) -> web.Response:
        """Receive GitHub PR events and advance AWAITING_REVIEW workflows.

        On `pull_request closed + merged` or `pull_request_review approved`,
        extracts build_id from the branch (`auto-heal/{build_id}`) and
        advances workflow → APPLYING_FIX → COMPLETED.
        """
        body = await request.read()
        if _webhook_secret() and not self._verify_github_signature(body, request):
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
                logger.info("github_pr_approved build_id=%s branch=%s",
                            build_id, branch)
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
            _webhook_secret().encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)
