"""Agent 4 support: fetch source files from local fs, GitHub, or Gerrit."""
from __future__ import annotations

import base64
import logging
import os
import pathlib

import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


class CodeFetcher:
    """Fetch file contents from a configured source backend.

    Args:
        mode: ``"local"`` | ``"github"`` | ``"gerrit"``
    """

    def __init__(self, mode: str = "local") -> None:
        self.mode = mode

    async def fetch_file(
        self, repo: str, file_path: str, ref: str = "main"
    ) -> str:
        """Return the text content of *file_path* at *ref*."""
        if self.mode == "github":
            return await self._github_fetch(repo, file_path, ref)
        if self.mode == "gerrit":
            return await self._gerrit_fetch(repo, file_path, ref)
        return self._local_fetch(file_path)

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _local_fetch(self, file_path: str) -> str:
        p = pathlib.Path(file_path)
        if not p.exists():
            logger.warning("local_fetch file_not_found path=%s", file_path)
            return ""
        return p.read_text(encoding="utf-8")

    async def _github_fetch(self, repo: str, file_path: str, ref: str) -> str:
        url = f"{_GITHUB_API}/repos/{repo}/contents/{file_path}?ref={ref}"
        headers = {"Authorization": f"token {_GITHUB_TOKEN}"} if _GITHUB_TOKEN else {}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", "")
            return base64.b64decode(content).decode("utf-8")

    async def _gerrit_fetch(self, repo: str, file_path: str, ref: str) -> str:
        gerrit_url = os.getenv("GERRIT_URL", "http://localhost:8083")
        url = (
            f"{gerrit_url}/a/projects/{repo}/branches/{ref}"
            f"/files/{file_path}/content"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
