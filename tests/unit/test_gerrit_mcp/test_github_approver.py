"""Unit tests for GitHub approval checker."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.gerrit_mcp.github_approver import (
    check_pr_approved,
    check_pr_merged,
    extract_build_id,
)


class TestExtractBuildId:
    def test_valid_branch(self):
        assert extract_build_id("auto-heal/build-42") == "build-42"

    def test_nested_build_id(self):
        assert extract_build_id("auto-heal/jenkins-123") == "jenkins-123"

    def test_unrelated_branch_returns_empty(self):
        assert extract_build_id("feature/my-feature") == ""

    def test_empty_string_returns_empty(self):
        assert extract_build_id("") == ""

    def test_prefix_only_returns_empty(self):
        # "auto-heal/" with nothing after prefix separator
        assert extract_build_id("auto-heal/") == ""


class TestCheckPrMerged:
    @respx.mock
    @pytest.mark.asyncio
    async def test_merged_pr_returns_true(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/7").mock(
            return_value=httpx.Response(200, json={"merged": True, "state": "closed"})
        )
        result = await check_pr_merged("org/repo", 7)
        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_open_pr_returns_false(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/8").mock(
            return_value=httpx.Response(200, json={"merged": False, "state": "open"})
        )
        result = await check_pr_merged("org/repo", 8)
        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_not_found_returns_false(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/99").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        result = await check_pr_merged("org/repo", 99)
        assert result is False


class TestCheckPrApproved:
    @respx.mock
    @pytest.mark.asyncio
    async def test_approved_review_returns_true(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/1/reviews").mock(
            return_value=httpx.Response(200, json=[
                {"user": {"login": "alice"}, "state": "APPROVED"},
            ])
        )
        result = await check_pr_approved("org/repo", 1)
        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_changes_requested_returns_false(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/2/reviews").mock(
            return_value=httpx.Response(200, json=[
                {"user": {"login": "alice"}, "state": "APPROVED"},
                {"user": {"login": "bob"},   "state": "CHANGES_REQUESTED"},
            ])
        )
        result = await check_pr_approved("org/repo", 2)
        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_reviews_returns_false(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/3/reviews").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await check_pr_approved("org/repo", 3)
        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_comment_only_not_counted(self):
        respx.get("https://api.github.com/repos/org/repo/pulls/4/reviews").mock(
            return_value=httpx.Response(200, json=[
                {"user": {"login": "alice"}, "state": "COMMENTED"},
            ])
        )
        result = await check_pr_approved("org/repo", 4)
        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_latest_review_per_reviewer_wins(self):
        """If a reviewer first requested changes but later approved, result is approved."""
        respx.get("https://api.github.com/repos/org/repo/pulls/5/reviews").mock(
            return_value=httpx.Response(200, json=[
                {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"},
                {"user": {"login": "alice"}, "state": "APPROVED"},
            ])
        )
        result = await check_pr_approved("org/repo", 5)
        assert result is True
