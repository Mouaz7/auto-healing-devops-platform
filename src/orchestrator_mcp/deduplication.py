"""Error fingerprint deduplication.

Prevents the pipeline from re-running expensive AI analysis on identical
errors within a configurable time window. This matters because:
  1. GitHub Actions can trigger the same failure multiple times (e.g. due to
     re-runs or simultaneous pushes).
  2. If a RED fix is produced, the root cause hasn't changed — running the
     pipeline again immediately will produce the same RED result.

Algorithm:
  - Fingerprint = MD5(error_type + ":" + root_cause[:200] + ":" + sorted_files)
  - Cache: fingerprint → (timestamp, build_id_first_seen)
  - If fingerprint seen within DEDUP_WINDOW_SECONDS → skip, return cached result
  - Expired entries cleaned up on every check

Usage:
    from src.orchestrator_mcp.deduplication import dedup_cache

    # Before running the pipeline:
    existing = dedup_cache.check(error_type, root_cause, affected_files)
    if existing:
        return existing  # {"build_id": ..., "colour": ..., "deduplicated": True}

    # After the pipeline completes:
    dedup_cache.record(error_type, root_cause, affected_files,
                       build_id=build_id, colour=colour, pr_url=pr_url)
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Identical errors seen within this window are deduplicated (24 hours)
DEDUP_WINDOW_SECONDS: float = 24 * 3600


@dataclass
class _CacheEntry:
    fingerprint: str
    build_id: str
    colour: str
    pr_url: str
    created_at: float   # time.time()


def _make_fingerprint(error_type: str, root_cause: str, affected_files: list[str]) -> str:
    """Stable hash of the error signature — independent of build_id or timestamp."""
    files_key = ",".join(sorted(affected_files))
    raw = f"{error_type}:{root_cause[:200]}:{files_key}"
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()


class DeduplicationCache:
    """Thread-safe in-memory cache for error fingerprints.

    Expired entries are evicted lazily on each check() or record() call
    so the dict stays bounded without a background thread.
    """

    def __init__(self, window_seconds: float = DEDUP_WINDOW_SECONDS) -> None:
        self._window = window_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        error_type: str,
        root_cause: str,
        affected_files: list[str],
    ) -> dict | None:
        """Return cached result if this error was seen recently, else None.

        Args:
            error_type: Enum value string (e.g. "ASSERTION_ERROR").
            root_cause: Short description from Agent 4.
            affected_files: List of affected file paths.

        Returns:
            Dict with build_id / colour / pr_url / deduplicated=True, or None.
        """
        fp = _make_fingerprint(error_type, root_cause, affected_files)
        now = time.time()

        with self._lock:
            self._evict_expired(now)
            entry = self._cache.get(fp)

        if entry:
            age_minutes = (now - entry.created_at) / 60
            logger.info(
                "dedup_hit fingerprint=%s build_id=%s age_min=%.1f",
                fp[:8], entry.build_id, age_minutes,
            )
            return {
                "build_id":      entry.build_id,
                "colour":        entry.colour,
                "pr_url":        entry.pr_url,
                "deduplicated":  True,
                "original_build": entry.build_id,
                "cache_age_min": round(age_minutes, 1),
            }
        return None

    def record(
        self,
        error_type: str,
        root_cause: str,
        affected_files: list[str],
        build_id: str,
        colour: str,
        pr_url: str = "",
    ) -> None:
        """Store the result for this error fingerprint.

        Should be called after a pipeline run completes (GREEN/YELLOW/RED).
        RED results are also cached so we don't waste tokens on the same
        unfixable error multiple times.
        """
        fp = _make_fingerprint(error_type, root_cause, affected_files)
        entry = _CacheEntry(
            fingerprint=fp,
            build_id=build_id,
            colour=colour,
            pr_url=pr_url,
            created_at=time.time(),
        )
        with self._lock:
            self._cache[fp] = entry
        logger.info(
            "dedup_recorded fingerprint=%s build_id=%s colour=%s",
            fp[:8], build_id, colour,
        )

    def size(self) -> int:
        """Return the number of active (non-expired) cache entries."""
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            return len(self._cache)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _evict_expired(self, now: float) -> None:
        """Remove entries older than the dedup window. Must be called with lock."""
        cutoff = now - self._window
        stale = [fp for fp, e in self._cache.items() if e.created_at < cutoff]
        for fp in stale:
            del self._cache[fp]
        if stale:
            logger.debug("dedup_evicted count=%d", len(stale))


# Global singleton
dedup_cache = DeduplicationCache()
