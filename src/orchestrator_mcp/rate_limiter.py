"""Sliding-window rate limiter for the orchestrator API.

Protects /tools/handle_build_failure from:
  - Accidental loops (e.g. a GitHub Actions workflow that misfires repeatedly)
  - Intentional abuse (token exhaustion attacks)

Algorithm: sliding window counter per key (IP or build_id prefix).
  - Window: 60 seconds
  - Default limit: 10 requests per window per key
  - When exceeded: returns 429 Too Many Requests

Usage (inside an aiohttp handler):

    from src.orchestrator_mcp.rate_limiter import rate_limiter

    key = request.remote or "unknown"
    if not rate_limiter.is_allowed(key):
        return web.json_response(
            {"error": "rate_limit_exceeded", "retry_after": 60},
            status=429,
        )
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# Default policy — override in tests or via env vars
_WINDOW_SECONDS: float = 60.0
_MAX_REQUESTS: int = 10


class RateLimiter:
    """Thread-safe sliding-window rate limiter.

    Each unique *key* (e.g. client IP, GitHub repo) gets its own request
    timestamp deque. Requests older than the window are evicted on each call
    so memory stays bounded.

    Args:
        window_seconds: Length of the sliding window in seconds.
        max_requests: Maximum allowed requests within *window_seconds*.
    """

    def __init__(
        self,
        window_seconds: float = _WINDOW_SECONDS,
        max_requests: int = _MAX_REQUESTS,
    ) -> None:
        self._window = window_seconds
        self._max = max_requests
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Return True if *key* is within its request budget.

        Side effect: records the current request timestamp on True.
        """
        now = time.time()
        cutoff = now - self._window

        with self._lock:
            ts = self._timestamps[key]

            # Evict timestamps older than the window
            while ts and ts[0] < cutoff:
                ts.popleft()

            if len(ts) >= self._max:
                logger.warning(
                    "rate_limit_exceeded key=%s count=%d limit=%d window=%.0fs",
                    key, len(ts), self._max, self._window,
                )
                return False

            ts.append(now)
            return True

    def current_count(self, key: str) -> int:
        """Return how many requests *key* has made in the current window."""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            ts = self._timestamps[key]
            while ts and ts[0] < cutoff:
                ts.popleft()
            return len(ts)

    def reset(self, key: str) -> None:
        """Clear all recorded timestamps for *key* (useful in tests)."""
        with self._lock:
            self._timestamps.pop(key, None)

    def stats(self) -> dict[str, int]:
        """Return current request counts per active key."""
        now = time.time()
        cutoff = now - self._window
        result: dict[str, int] = {}
        with self._lock:
            for key, ts in self._timestamps.items():
                while ts and ts[0] < cutoff:
                    ts.popleft()
                if ts:
                    result[key] = len(ts)
        return result


# Global singleton — 10 requests / 60 s per client IP
rate_limiter = RateLimiter(window_seconds=60.0, max_requests=10)
