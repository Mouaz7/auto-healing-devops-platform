"""Create GitHub pull requests for auto-generated fixes.

Flow:
  1. Get the current SHA of the target file on the base branch.
  2. Create a new branch  ``auto-heal/{build_id}``.
  3. Commit the fixed file content to that branch.
  4. Open a PR against the base branch.

The branch name encodes the build_id so the orchestrator's GitHub webhook
can recover the build_id when the PR is merged/approved.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]  # exponential backoff


class PatchSubmitter:
    """Submit a code fix as a GitHub pull request."""

    def __init__(self) -> None:
        self._token = os.getenv("GITHUB_TOKEN", "")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_pr(
        self,
        repo: str,
        build_id: str,
        patch: str,
        affected_files: list[str],
        title: str = "",
        base_branch: str = "main",
    ) -> dict[str, object]:
        """Create a GitHub PR with the fix.

        Args:
            repo: ``owner/repo`` format.
            build_id: Used as the branch name suffix.
            patch: Fixed file content (output from Agent 5).
            affected_files: Files changed by the fix.
            title: PR title (auto-generated if empty).
            base_branch: Target branch for the PR.

        Returns:
            ``{"pr_url": str, "pr_number": int, "branch": str}``
        """
        if not self._token:
            logger.warning("create_pr skipped — GITHUB_TOKEN not set")
            return {"pr_url": "", "pr_number": 0, "branch": ""}

        branch = f"auto-heal/{build_id}"
        pr_title = title or f"[auto-heal] Fix for build {build_id}"
        file_path = affected_files[0] if affected_files else "auto_heal_fix.py"

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=15, headers=self._headers
                ) as client:
                    base_sha = await self._get_base_sha(client, repo, base_branch)
                    await self._create_branch(client, repo, branch, base_sha)
                    await self._commit_file(
                        client, repo, branch, file_path, patch,
                        f"auto-heal: fix for build {build_id}",
                    )
                    pr = await self._open_pr(
                        client, repo, pr_title, branch, base_branch,
                        build_id, affected_files, patch,
                    )
                    logger.info(
                        "pr_created repo=%s build_id=%s pr_number=%d url=%s",
                        repo, build_id, pr["number"], pr["html_url"],
                    )
                    return {
                        "pr_url":    pr["html_url"],
                        "pr_number": pr["number"],
                        "branch":    branch,
                    }
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 422:
                    # Branch already exists — treat as success if PR exists
                    logger.warning("branch_exists build_id=%s attempt=%d", build_id, attempt)
                    return {"pr_url": "", "pr_number": 0, "branch": branch}
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                else:
                    raise

        raise RuntimeError("create_pr: max retries exhausted")

    # ------------------------------------------------------------------
    # Private GitHub API helpers
    # ------------------------------------------------------------------

    async def _get_base_sha(
        self, client: httpx.AsyncClient, repo: str, branch: str
    ) -> str:
        resp = await client.get(
            f"{_GITHUB_API}/repos/{repo}/git/ref/heads/{branch}"
        )
        resp.raise_for_status()
        return str(resp.json()["object"]["sha"])

    async def _create_branch(
        self, client: httpx.AsyncClient, repo: str, branch: str, sha: str
    ) -> None:
        resp = await client.post(
            f"{_GITHUB_API}/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        resp.raise_for_status()

    async def _commit_file(
        self,
        client: httpx.AsyncClient,
        repo: str,
        branch: str,
        file_path: str,
        content: str,
        message: str,
    ) -> None:
        # Get current file SHA (needed for update)
        current_sha = ""
        check = await client.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{file_path}",
            params={"ref": branch},
        )
        if check.status_code == 200:
            current_sha = check.json().get("sha", "")

        body: dict[str, object] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch":  branch,
        }
        if current_sha:
            body["sha"] = current_sha

        resp = await client.put(
            f"{_GITHUB_API}/repos/{repo}/contents/{file_path}", json=body
        )
        resp.raise_for_status()

    async def _open_pr(
        self,
        client: httpx.AsyncClient,
        repo: str,
        title: str,
        head: str,
        base: str,
        build_id: str,
        affected_files: list[str],
        patch: str,
    ) -> dict:
        body = (
            f"## Auto-Heal Fix — build `{build_id}`\n\n"
            f"**Affected files:** {', '.join(affected_files) or 'none'}\n\n"
            f"```python\n{patch[:2000]}\n```\n\n"
            "_Generated by the Auto-Healing AI DevOps Platform._"
        )
        resp = await client.post(
            f"{_GITHUB_API}/repos/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        resp.raise_for_status()
        return dict(resp.json())
