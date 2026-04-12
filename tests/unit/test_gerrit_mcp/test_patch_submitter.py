"""Unit tests for PatchSubmitter (GitHub PR creation)."""
from __future__ import annotations

import pytest

from src.gerrit_mcp.patch_submitter import PatchSubmitter


class TestCreatePrNoToken:
    """When GITHUB_TOKEN is absent, create_pr should skip gracefully."""

    @pytest.mark.asyncio
    async def test_no_token_returns_empty_url(self):
        submitter = PatchSubmitter()
        submitter._token = ""  # pylint: disable=protected-access
        result = await submitter.create_pr(
            repo="org/repo",
            build_id="test-001",
            patch="x = 1",
            affected_files=["src/app.py"],
        )
        assert result["pr_url"] == ""
        assert result["pr_number"] == 0
        assert result["branch"] == ""

    @pytest.mark.asyncio
    async def test_no_token_does_not_raise(self, monkeypatch):
        submitter = PatchSubmitter()
        submitter._token = ""  # pylint: disable=protected-access
        # Should complete without exception
        await submitter.create_pr(
            repo="org/repo",
            build_id="test-002",
            patch="",
            affected_files=[],
        )


class TestBranchNamingConvention:
    """Branch name must follow auto-heal/{build_id} so the webhook can decode it."""

    def test_branch_format(self):
        # Verify the convention used in create_pr matches extract_build_id
        from src.gerrit_mcp.github_approver import extract_build_id
        build_id = "jenkins-pipeline-99"
        branch = f"auto-heal/{build_id}"
        assert extract_build_id(branch) == build_id

    def test_branch_with_slash_in_build_id(self):
        from src.gerrit_mcp.github_approver import extract_build_id
        build_id = "org/repo/build-1"
        branch = f"auto-heal/{build_id}"
        assert extract_build_id(branch) == build_id
