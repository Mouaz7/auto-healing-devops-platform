"""Additional tests for PatchSubmitter to boost coverage."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.gerrit_mcp.patch_submitter import PatchSubmitter


class TestCreatePrNoToken:
    @pytest.mark.asyncio
    async def test_no_token_returns_empty(self, monkeypatch):
        """Without GITHUB_TOKEN, returns empty result dict."""
        monkeypatch.setenv("GITHUB_TOKEN", "")
        from src.gerrit_mcp import patch_submitter as ps_module
        import importlib
        importlib.reload(ps_module)

        submitter = ps_module.PatchSubmitter()
        result = await submitter.create_pr("owner/repo", "build-1", "patch", [])
        assert result["pr_url"] == ""
        assert result["pr_number"] == 0


class TestCreatePrSuccess:
    @respx.mock
    @pytest.mark.asyncio
    async def test_full_pr_creation_flow(self, monkeypatch):
        """Full PR creation flow: get SHA → create branch → commit → open PR."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        from src.gerrit_mcp import patch_submitter as ps_module
        import importlib
        importlib.reload(ps_module)

        respx.get("https://api.github.com/repos/owner/repo/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={"object": {"sha": "abc123"}})
        )
        respx.post("https://api.github.com/repos/owner/repo/git/refs").mock(
            return_value=httpx.Response(201, json={})
        )
        # File doesn't exist yet (404) → new file
        respx.get("https://api.github.com/repos/owner/repo/contents/src/app.py").mock(
            return_value=httpx.Response(404)
        )
        respx.put("https://api.github.com/repos/owner/repo/contents/src/app.py").mock(
            return_value=httpx.Response(201, json={})
        )
        respx.post("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(201, json={
                "html_url": "https://github.com/owner/repo/pull/42",
                "number": 42,
            })
        )

        submitter = ps_module.PatchSubmitter()
        result = await submitter.create_pr(
            repo="owner/repo",
            build_id="build-1",
            patch="from lib import Foo",
            affected_files=["src/app.py"],
        )

        assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert result["pr_number"] == 42
        assert result["branch"] == "auto-heal/build-1"


class TestCreatePrBranchExists:
    @respx.mock
    @pytest.mark.asyncio
    async def test_422_returns_empty_pr_url(self, monkeypatch):
        """422 on branch creation (already exists) → returns empty pr_url."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        from src.gerrit_mcp import patch_submitter as ps_module
        import importlib
        importlib.reload(ps_module)

        respx.get("https://api.github.com/repos/owner/repo/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={"object": {"sha": "abc123"}})
        )
        respx.post("https://api.github.com/repos/owner/repo/git/refs").mock(
            return_value=httpx.Response(422, json={"message": "Reference already exists"})
        )

        submitter = ps_module.PatchSubmitter()
        result = await submitter.create_pr(
            repo="owner/repo",
            build_id="existing-build",
            patch="code",
            affected_files=["src/foo.py"],  # required: no-file = reject PR
        )
        assert result["pr_url"] == ""
        assert result["branch"] == "auto-heal/existing-build"


class TestHelpers:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_base_sha_returns_sha(self, monkeypatch):
        """_get_base_sha extracts SHA from GitHub API response."""
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        from src.gerrit_mcp import patch_submitter as ps_module
        import importlib
        importlib.reload(ps_module)

        respx.get("https://api.github.com/repos/owner/repo/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={"object": {"sha": "def456"}})
        )

        submitter = ps_module.PatchSubmitter()
        async with httpx.AsyncClient(headers=submitter._headers) as client:
            sha = await submitter._get_base_sha(client, "owner/repo", "main")
        assert sha == "def456"
