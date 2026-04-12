"""Log fetcher for Agent 1 — retrieves raw console output from Jenkins."""
from __future__ import annotations

import logging
import pathlib

import httpx

from src.shared.config import SERVICE_URLS

logger = logging.getLogger(__name__)

_FIXTURES_DIR = pathlib.Path("tests/fixtures/sample_jenkins_logs")


class LogFetcher:
    """Fetches raw build logs from Jenkins.

    Args:
        mock_mode: If True, returns fixture files instead of hitting Jenkins.
                   Enabled by default for dev/test environments.
    """

    def __init__(self, mock_mode: bool = True) -> None:
        self.mock_mode = mock_mode

    async def fetch(self, job_name: str, build_id: str) -> str:
        """Fetch raw console output for a build.

        Args:
            job_name: Jenkins job name.
            build_id: Build number or ID.

        Returns:
            Raw log text.

        Raises:
            httpx.HTTPStatusError: If Jenkins returns a non-2xx response.
        """
        if self.mock_mode:
            return self._load_fixture(build_id)

        url = f"{SERVICE_URLS['jenkins']}/job/{job_name}/{build_id}/consoleText"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            logger.info("log_fetched build_id=%s bytes=%d", build_id, len(resp.text))
            return resp.text

    def _load_fixture(self, build_id: str) -> str:
        """Return fixture log. Uses import_error log as default."""
        fixture_map = {
            "syntax": _FIXTURES_DIR / "build_failure_syntax_error.log",
            "success": _FIXTURES_DIR / "build_success.log",
        }
        for key, path in fixture_map.items():
            if key in build_id.lower() and path.exists():
                return path.read_text(encoding="utf-8")

        default = _FIXTURES_DIR / "build_failure_import_error.log"
        if default.exists():
            return default.read_text(encoding="utf-8")

        # Minimal fallback if fixture files are absent
        return (
            "ERROR: ImportError: cannot import name Config\n"
            "Traceback (most recent call last):\n"
            "  File src/main.py, line 1\n"
            "ImportError: cannot import name Config\n"
        )
