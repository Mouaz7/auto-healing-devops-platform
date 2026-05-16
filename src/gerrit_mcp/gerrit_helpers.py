"""Helpers for the GitHub PR submitter — pure logic, no I/O.

Kept module-level so they can be unit-tested without an HTTP client.
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)


# Hallucinated / placeholder filenames that LLMs sometimes emit when they
# can't identify a real file. We refuse to create PRs against these — the
# filename would end up literally committed to the branch.
_BAD_FILENAMES = {
    "<unknown>", "(unknown)", "unknown", "unknown.py",
    "<file>", "<filename>", "<path>", "placeholder.py",
    "example.py", "auto_heal_fix.py", "file.py",
}

# Critical paths that auto-heal MUST NEVER modify.
# Modifying these creates infrastructure failures: workflow loops, broken CI,
# overwritten dependencies. AI fixes belong in application code only.
_PROTECTED_PATH_PREFIXES = (
    ".github/",          # CI workflow files — overwriting these breaks auto-heal itself
    ".gitlab/",
    ".circleci/",
    ".azure/",
    ".husky/",
    "Dockerfile",
    "docker-compose",
    "Makefile",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    ".env",
    ".gitignore",
    "LICENSE",
)

GITHUB_API = "https://api.github.com"
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]  # exponential backoff (seconds)
MAX_RATE_LIMIT_WAIT = 60.0       # never wait more than 60 s for rate-limit recovery


def is_protected_path(path: str) -> bool:
    """Return True for paths the AI must never modify (CI, deps, infra)."""
    p = path.lstrip("./").lower()
    return any(p.startswith(prefix.lower()) for prefix in _PROTECTED_PATH_PREFIXES)


def sanitize_files(files: list[str]) -> list[str]:
    """Drop empty, hallucinated, protected, or non-Python paths.

    NOTE: Only .py files are accepted. The patch-submission flow writes
    the fixed content directly to GitHub via the contents API using
    base64-encoded bytes, which requires knowing the exact encoding.
    Python source files are UTF-8 by PEP 3120; supporting other languages
    (Go, TypeScript, Java, etc.) would require per-language encoding logic.
    This is a known limitation — extend this filter when multi-language
    patch submission is implemented.
    """
    result: list[str] = []
    for f in files or []:
        if not f:
            continue
        f = f.strip()
        if f.lower() in _BAD_FILENAMES:
            continue
        if f.startswith("<") or f.startswith("("):
            continue
        if any(c in f for c in "<>()[]{}"):
            continue
        if is_protected_path(f):
            logger.warning("rejecting protected path from AI fix: %s", f)
            continue
        if not f.endswith(".py"):
            logger.debug("sanitize_files: skipping non-Python file %s", f)
            continue
        result.append(f.lstrip("./"))
    return result


def rate_limit_wait(response: httpx.Response) -> float:
    """Seconds to wait after a 403/429 rate-limit response.

    Honours `Retry-After`, then `X-RateLimit-Reset`. Capped at 60 s so a
    misconfigured server header can't pause the pipeline indefinitely.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), MAX_RATE_LIMIT_WAIT)
        except ValueError:
            pass
    reset_ts = response.headers.get("X-RateLimit-Reset")
    if reset_ts:
        try:
            wait = float(reset_ts) - time.time()
            return min(max(wait, 0.0), MAX_RATE_LIMIT_WAIT)
        except ValueError:
            pass
    return 5.0
