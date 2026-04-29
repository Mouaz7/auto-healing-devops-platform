"""Structured audit log — append-only JSONL event stream.

Every significant action in the pipeline is recorded here:
  - pipeline_start / pipeline_complete / pipeline_failed
  - fix_generated / fix_deduplicated
  - pr_created / pr_approved / pr_rejected / review_timeout
  - rate_limit_blocked

The audit log is essential for thesis evaluation: it provides the empirical
dataset for measuring auto-fix success rates, latency, and cost over time.

Format: one JSON object per line (JSONL / newline-delimited JSON).
  {"ts":"2026-04-23T12:00:00Z","event":"pipeline_start","build_id":"123",...}

Usage:
    from src.shared.audit_log import audit
    audit.log("pipeline_complete", build_id="123", colour="GREEN", pr_url="...")
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Audit log path — override with AUDIT_LOG_PATH env var
_DEFAULT_LOG_PATH = "/var/log/auto-healer/audit.jsonl"


class AuditLog:
    """Thread-safe append-only JSONL audit log.

    Each call to log() atomically appends one line to the log file.
    The file is created (with parent directories) on first write.
    If the file cannot be opened, events are emitted to the Python logger
    instead so the pipeline is never blocked by audit failures.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path or os.getenv("AUDIT_LOG_PATH", _DEFAULT_LOG_PATH))
        self._lock = threading.Lock()
        self._ready = False
        self._init_file()

    def _init_file(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Touch the file to verify write permission early
            self._path.touch(exist_ok=True)
            self._ready = True
            logger.info("audit_log_path=%s", self._path)
        except OSError as exc:
            logger.warning("audit_log_unavailable path=%s error=%s", self._path, exc)

    def log(self, event: str, **kwargs: Any) -> None:
        """Append an audit event.

        Args:
            event: Event name (snake_case string).
            **kwargs: Arbitrary key-value pairs to include in the record.
        """
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "event": event,
        }
        record.update(kwargs)
        line = json.dumps(record, default=str) + "\n"

        if not self._ready:
            logger.info("audit_event %s", line.rstrip())
            return

        try:
            with self._lock, open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            # Never crash the pipeline due to audit failure
            logger.warning("audit_write_failed event=%s error=%s", event, exc)
            logger.info("audit_event %s", line.rstrip())

    def tail(self, n: int = 100) -> list[dict]:
        """Return the last *n* audit records (newest last).

        Useful for the /api/stats endpoint and thesis data collection.
        """
        if not self._ready or not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            records = []
            for line in lines[-n:]:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return records
        except OSError:
            return []

    def summary(self) -> dict[str, int]:
        """Return event-type counts across the full log (for /api/stats)."""
        counts: dict[str, int] = {}
        if not self._ready or not self._path.exists():
            return counts
        try:
            with open(self._path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ev = rec.get("event", "unknown")
                        counts[ev] = counts.get(ev, 0) + 1
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
        return counts


# Global singleton
audit = AuditLog()
