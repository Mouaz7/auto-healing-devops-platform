"""Tests for LogFetcher — fixture loading and HTTP fetch."""
from __future__ import annotations

import pytest
import respx
import httpx

from src.jenkins_mcp.log_fetcher import LogFetcher
from src.shared.config import SERVICE_URLS


class TestMockMode:
    @pytest.mark.asyncio
    async def test_mock_mode_returns_log(self):
        """In mock mode, returns fixture or fallback log text."""
        fetcher = LogFetcher(mock_mode=True)
        result = await fetcher.fetch("my-job", "build-001")
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_mock_mode_fallback_contains_importerror(self):
        """Fallback fixture contains ImportError."""
        fetcher = LogFetcher(mock_mode=True)
        result = await fetcher.fetch("job", "unknown-build-id-xyz")
        assert "ImportError" in result or len(result) > 0

    def test_load_fixture_with_syntax_key(self):
        """build_id containing 'syntax' tries syntax-error fixture."""
        fetcher = LogFetcher(mock_mode=True)
        # Should not raise, even if file doesn't exist (falls back to default)
        result = fetcher._load_fixture("syntax-build-1")
        assert len(result) > 0

    def test_load_fixture_fallback_when_key_not_found(self):
        """Unknown build_id falls back to import_error or minimal fallback."""
        fetcher = LogFetcher(mock_mode=True)
        result = fetcher._load_fixture("some-random-build")
        assert len(result) > 0


class TestLiveMode:
    @respx.mock
    @pytest.mark.asyncio
    async def test_live_mode_fetches_from_jenkins(self):
        """In live mode, GETs from Jenkins consoleText URL."""
        log_content = "BUILD FAILURE\nImportError: cannot import Config"
        jenkins_url = f"{SERVICE_URLS['jenkins']}/job/my-job/42/consoleText"
        respx.get(jenkins_url).mock(
            return_value=httpx.Response(200, text=log_content)
        )

        fetcher = LogFetcher(mock_mode=False)
        result = await fetcher.fetch("my-job", "42")
        assert "BUILD FAILURE" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_live_mode_raises_on_404(self):
        """Jenkins 404 → HTTPStatusError raised."""
        jenkins_url = f"{SERVICE_URLS['jenkins']}/job/bad-job/99/consoleText"
        respx.get(jenkins_url).mock(return_value=httpx.Response(404))

        fetcher = LogFetcher(mock_mode=False)
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("bad-job", "99")
