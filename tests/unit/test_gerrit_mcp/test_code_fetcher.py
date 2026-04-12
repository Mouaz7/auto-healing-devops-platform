"""Tests for CodeFetcher — local, github, gerrit backends."""
from __future__ import annotations

import pathlib
import tempfile

import pytest
import respx
import httpx

from src.gerrit_mcp.code_fetcher import CodeFetcher


class TestLocalFetch:
    @pytest.mark.asyncio
    async def test_existing_file_returned(self, tmp_path):
        """Local file content returned correctly."""
        f = tmp_path / "app.py"
        f.write_text("def hello(): pass\n", encoding="utf-8")

        fetcher = CodeFetcher(mode="local")
        result = await fetcher.fetch_file("", str(f))
        assert "def hello" in result

    @pytest.mark.asyncio
    async def test_missing_file_returns_empty(self):
        """Non-existent file returns empty string."""
        fetcher = CodeFetcher(mode="local")
        result = await fetcher.fetch_file("", "/nonexistent/path/file.py")
        assert result == ""

    @pytest.mark.asyncio
    async def test_local_mode_default(self):
        """Default mode is 'local'."""
        fetcher = CodeFetcher()
        assert fetcher.mode == "local"


class TestGitHubFetch:
    @respx.mock
    @pytest.mark.asyncio
    async def test_github_fetch_decodes_base64(self):
        """GitHub API response is base64-decoded."""
        import base64
        content = "def greet(): return 'hello'"
        encoded = base64.b64encode(content.encode()).decode()

        respx.get("https://api.github.com/repos/owner/repo/contents/src/app.py?ref=main").mock(
            return_value=httpx.Response(200, json={"content": encoded + "\n"})
        )

        fetcher = CodeFetcher(mode="github")
        result = await fetcher.fetch_file("owner/repo", "src/app.py", ref="main")
        assert "def greet" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_github_fetch_raises_on_404(self):
        """GitHub 404 raises HTTPStatusError."""
        respx.get("https://api.github.com/repos/owner/repo/contents/missing.py?ref=main").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        fetcher = CodeFetcher(mode="github")
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch_file("owner/repo", "missing.py", ref="main")


class TestGerritFetch:
    @respx.mock
    @pytest.mark.asyncio
    async def test_gerrit_fetch_returns_text(self, monkeypatch):
        """Gerrit API response text is returned."""
        import src.gerrit_mcp.code_fetcher as cf_module
        monkeypatch.setitem(cf_module.SERVICE_URLS, "gerrit", "http://gerrit.example.com")

        respx.get(
            "http://gerrit.example.com/a/projects/my-repo/branches/main/files/src/app.py/content"
        ).mock(return_value=httpx.Response(200, text="class Foo: pass"))

        fetcher = cf_module.CodeFetcher(mode="gerrit")
        result = await fetcher.fetch_file("my-repo", "src/app.py", ref="main")
        assert "class Foo" in result
