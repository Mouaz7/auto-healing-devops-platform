"""GitHub PR approval checker.

Used by the orchestrator to verify that a PR has been approved / merged
before advancing the workflow from AWAITING_REVIEW → APPLYING_FIX.

Two entry points:
  - ``check_pr_merged``  — called by the GitHub webhook handler (instant)
  - ``check_pr_approved`` — called to verify review status
  - ``extract_build_id`` — recovers build_id from branch name ``auto-heal/{id}``
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if _GITHUB_TOKEN:
        h["Authorization"] = f"token {_GITHUB_TOKEN}"
    return h


def extract_build_id(branch_name: str) -> str:
    """Return the build_id encoded in an ``auto-heal/{build_id}`` branch.

    Returns an empty string if the branch does not follow the convention.
    """
    prefix = "auto-heal/"
    if branch_name.startswith(prefix):
        return branch_name[len(prefix):]
    return ""


async def check_pr_merged(repo: str, pr_number: int) -> bool:
    """Return True if the GitHub PR has been merged."""
    url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    async with httpx.AsyncClient(timeout=10, headers=_headers()) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get("merged"))


async def check_pr_approved(repo: str, pr_number: int) -> bool:
    """Return True if the PR has ≥1 APPROVED review and no CHANGES_REQUESTED.

    GitHub review states: APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED.
    Only the latest review per reviewer is considered.
    """
    url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews"
    async with httpx.AsyncClient(timeout=10, headers=_headers()) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        reviews = resp.json()

    # Keep only the latest review per reviewer
    latest: dict[str, str] = {}
    for review in reviews:
        user = review.get("user", {}).get("login", "")
        state = review.get("state", "")
        if user and state in {"APPROVED", "CHANGES_REQUESTED"}:
            latest[user] = state

    states = set(latest.values())
    has_approval = "APPROVED" in states
    has_block = "CHANGES_REQUESTED" in states

    logger.info(
        "pr_review_check repo=%s pr=%d approved=%s blocked=%s",
        repo, pr_number, has_approval, has_block,
    )
    return has_approval and not has_block
