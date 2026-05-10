"""Heal verifier — detects regressions after an AI fix is deployed.

After a GREEN auto-merge, the system remembers which files were fixed and when.
If the SAME files fail again within REGRESSION_WINDOW_MINUTES, a Slack alert
is sent immediately: the fix may have introduced a new bug or not solved the
root cause.

This closes the feedback loop:
  Fix deployed → Monitor → Regression? → Alert → Human investigates

Storage: in-memory dict (intentional — regressions are a real-time signal,
not a long-term store).  Survives within a container lifetime but resets on
restart, which is acceptable since the window is only 60 minutes.

Usage:
    from src.shared.heal_verifier import heal_verifier

    # After GREEN auto-merge:
    heal_verifier.record_fix(build_id, affected_files)

    # When a new failure comes in (before pipeline starts):
    regression = heal_verifier.check_regression(new_build_id, affected_files)
    if regression:
        # regression["original_build_id"] and regression["fixed_files"]
        await send_regression_alert(regression)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

REGRESSION_WINDOW_MINUTES = 60   # configurable via subclass / env var


@dataclass
class FixRecord:
    """One deployed fix."""

    build_id:       str
    fixed_files:    frozenset[str]
    merged_at:      float = field(default_factory=time.time)
    error_type:     str   = ""
    retry_count:    int   = 0


class HealVerifier:
    """Thread-safe regression detector.

    Keeps a rolling window of deployed fixes and checks new failures against
    recently fixed files.

    Args:
        window_minutes: How long after a fix to watch for regressions.
    """

    def __init__(self, window_minutes: int = REGRESSION_WINDOW_MINUTES) -> None:
        self._window = window_minutes * 60
        self._fixes:  dict[str, FixRecord] = {}   # build_id → FixRecord
        self._lock = threading.Lock()

    def record_fix(self, build_id: str, affected_files: list[str], error_type: str = "") -> None:
        """Record a successfully deployed fix.

        Args:
            build_id:       The build whose fix was merged.
            affected_files: Files that were modified by the fix.
            error_type:     The error type that was fixed (e.g. SYNTAX_ERROR).
        """
        record = FixRecord(
            build_id=build_id,
            fixed_files=frozenset(f for f in affected_files if f),
            error_type=error_type,
        )
        with self._lock:
            self._evict_stale()
            self._fixes[build_id] = record
        logger.info(
            "heal_verifier_recorded build_id=%s files=%s error_type=%s",
            build_id, list(record.fixed_files), error_type,
        )

    def check_regression(
        self,
        new_build_id: str,
        failing_files: list[str],
    ) -> dict[str, Any] | None:
        """Check if a new failure is a regression of a recently applied fix.

        Args:
            new_build_id:  The failing build being processed.
            failing_files: Files involved in the new failure.

        Returns:
            A regression info dict if detected, else ``None``.
            Keys: original_build_id, fixed_files, age_minutes, overlap_files.
        """
        if not failing_files:
            return None

        new_files = frozenset(f for f in failing_files if f)
        now = time.time()

        with self._lock:
            self._evict_stale()
            for bid, record in self._fixes.items():
                if bid == new_build_id:
                    continue
                overlap = record.fixed_files & new_files
                if not overlap:
                    continue
                age_seconds = now - record.merged_at
                age_minutes = round(age_seconds / 60, 1)
                logger.warning(
                    "regression_detected new_build=%s original_build=%s "
                    "overlap=%s age_min=%.1f",
                    new_build_id, bid, list(overlap), age_minutes,
                )
                return {
                    "original_build_id": bid,
                    "fixed_files":       list(record.fixed_files),
                    "overlap_files":     list(overlap),
                    "age_minutes":       age_minutes,
                    "error_type":        record.error_type,
                    "retry_count":       record.retry_count,
                }
        return None

    def increment_retry(self, original_build_id: str) -> None:
        """Mark that one regression retry has been allowed for this fix record."""
        with self._lock:
            if original_build_id in self._fixes:
                self._fixes[original_build_id].retry_count += 1

    def active_fixes(self) -> list[dict[str, Any]]:
        """Return all active (non-expired) fix records for monitoring."""
        with self._lock:
            self._evict_stale()
            return [
                {
                    "build_id":    r.build_id,
                    "fixed_files": list(r.fixed_files),
                    "age_minutes": round((time.time() - r.merged_at) / 60, 1),
                }
                for r in self._fixes.values()
            ]

    def _evict_stale(self) -> None:
        """Remove fix records older than the regression window (lock must be held)."""
        cutoff = time.time() - self._window
        stale = [bid for bid, r in self._fixes.items() if r.merged_at < cutoff]
        for bid in stale:
            del self._fixes[bid]
            logger.debug("heal_verifier_evicted build_id=%s", bid)


# Global singleton
heal_verifier = HealVerifier()
