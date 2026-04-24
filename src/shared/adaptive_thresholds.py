"""Adaptive confidence thresholds — the system learns from human decisions.

Standard traffic light thresholds (GREEN ≥ 0.85, YELLOW ≥ 0.60) are fixed.
This module makes them *per-error-type* and *self-calibrating*:

  • Each time a human approves a fix, we record the confidence score.
  • Each time a human rejects a fix, we record it.
  • When enough data accumulates for an error type, we shift the thresholds
    toward what humans actually accept (with a safety margin).

Example:
  The AI consistently produces ASSERTION_ERROR fixes with confidence 0.70.
  Humans approve them every time.  After 5 approvals the GREEN threshold
  for ASSERTION_ERROR drops from 0.85 → 0.72, so future fixes auto-merge
  instead of waiting for human review.

  Conversely, if humans reject TYPE_ERROR fixes even at 0.80, the GREEN
  threshold for that type rises to 0.88 to send more of them for review.

Storage: append-only JSONL (same pattern as fix_memory — no new deps).

Usage:
    from src.shared.adaptive_thresholds import adaptive_thresholds

    # After a human decision:
    adaptive_thresholds.record_decision(
        error_type="ASSERTION_ERROR", confidence=0.72, approved=True
    )

    # Before evaluating traffic light:
    green_t, yellow_t = adaptive_thresholds.get_thresholds("ASSERTION_ERROR")
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "/var/log/auto-healer/adaptive_thresholds.jsonl"

# Global safe bounds — thresholds never go outside these ranges
_GREEN_MIN  = 0.70   # never auto-merge below 70% even if humans always approve
_GREEN_MAX  = 0.95   # never require above 95% confidence for GREEN
_YELLOW_MIN = 0.45   # never block below 45%
_YELLOW_MAX = 0.80   # YELLOW threshold is always below GREEN threshold

# Require at least this many decisions before adapting
_MIN_DECISIONS = 5

# Safety margin applied after learning (conservative shift)
_SAFETY_MARGIN = 0.03

# Defaults (same as traffic_light_evaluator global values)
_DEFAULT_GREEN  = 0.85
_DEFAULT_YELLOW = 0.60


class AdaptiveThresholds:
    """Per-error-type, self-calibrating confidence thresholds.

    Thresholds are recalculated lazily when queried, from the full decision
    history for that error type.  The file is append-only so no records are
    lost and the threshold can be audited over time.

    Args:
        path: JSONL file path.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path or os.getenv("ADAPTIVE_THRESHOLDS_PATH", _DEFAULT_PATH))
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, float]] = {}  # error_type → (green, yellow)
        self._dirty: set[str] = set()                     # types needing recalc
        self._init_file()

    def _init_file(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch(exist_ok=True)
        except OSError as exc:
            logger.warning("adaptive_thresholds_unavailable path=%s error=%s", self._path, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_decision(self, error_type: str, confidence: float, approved: bool) -> None:
        """Record a human approve/reject decision.

        Args:
            error_type: Normalised error type (e.g. "ASSERTION_ERROR").
            confidence: The fix confidence score at decision time.
            approved:   True if human approved, False if rejected.
        """
        entry = {
            "ts":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error_type": error_type,
            "confidence": round(confidence, 4),
            "approved":   approved,
        }
        line = json.dumps(entry) + "\n"
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                self._dirty.add(error_type)
                self._cache.pop(error_type, None)   # invalidate cached threshold
        except OSError as exc:
            logger.warning("adaptive_thresholds_write_failed error=%s", exc)

        logger.info(
            "adaptive_threshold_decision error_type=%s confidence=%.2f approved=%s",
            error_type, confidence, approved,
        )

    def get_thresholds(self, error_type: str) -> tuple[float, float]:
        """Return (green_threshold, yellow_threshold) for *error_type*.

        Falls back to defaults when there are fewer than _MIN_DECISIONS.

        Args:
            error_type: Normalised error type string.

        Returns:
            Tuple of (green_threshold, yellow_threshold) floats.
        """
        with self._lock:
            if error_type in self._cache:
                return self._cache[error_type]

        records = self._load_for(error_type)
        thresholds = self._calculate(records)

        with self._lock:
            self._cache[error_type] = thresholds
        return thresholds

    def summary(self) -> dict[str, dict]:
        """Return current thresholds for all seen error types."""
        error_types = self._all_error_types()
        result = {}
        for et in error_types:
            green, yellow = self.get_thresholds(et)
            result[et] = {
                "green_threshold":  round(green, 3),
                "yellow_threshold": round(yellow, 3),
                "adapted":          green != _DEFAULT_GREEN or yellow != _DEFAULT_YELLOW,
            }
        return result

    def decision_history(self, error_type: str) -> list[dict]:
        """Return all recorded decisions for *error_type* (newest first)."""
        return list(reversed(self._load_for(error_type)))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate(self, records: list[dict]) -> tuple[float, float]:
        """Derive thresholds from a set of human decisions.

        Algorithm:
          - Separate approved vs rejected confidence scores.
          - The new GREEN threshold = mean(approved_scores) - SAFETY_MARGIN.
            "If humans approve at this average confidence, let the AI auto-merge
            slightly below that average."
          - The new YELLOW threshold = mean(rejected_scores) + SAFETY_MARGIN.
            "Scores near where humans reject should go for review."
          - Both are clamped to safe bounds.
          - Falls back to defaults if insufficient data.
        """
        approved   = [r["confidence"] for r in records if r.get("approved")]
        rejected   = [r["confidence"] for r in records if not r.get("approved")]

        green  = _DEFAULT_GREEN
        yellow = _DEFAULT_YELLOW

        if len(approved) >= _MIN_DECISIONS:
            candidate = mean(approved) - _SAFETY_MARGIN
            green = max(_GREEN_MIN, min(_GREEN_MAX, candidate))

        if len(rejected) >= _MIN_DECISIONS:
            candidate = mean(rejected) + _SAFETY_MARGIN
            yellow = max(_YELLOW_MIN, min(_YELLOW_MAX, candidate))

        # Ensure yellow < green always
        yellow = min(yellow, green - 0.10)

        return round(green, 3), round(yellow, 3)

    def _load_for(self, error_type: str) -> list[dict]:
        try:
            with self._lock:
                text = self._path.read_text(encoding="utf-8")
        except OSError:
            return []
        records = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("error_type") == error_type:
                    records.append(rec)
            except json.JSONDecodeError:
                pass
        return records

    def _all_error_types(self) -> set[str]:
        try:
            with self._lock:
                text = self._path.read_text(encoding="utf-8")
        except OSError:
            return set()
        types: set[str] = set()
        for line in text.splitlines():
            try:
                rec = json.loads(line.strip())
                if "error_type" in rec:
                    types.add(rec["error_type"])
            except json.JSONDecodeError:
                pass
        return types


# Global singleton
adaptive_thresholds = AdaptiveThresholds()
