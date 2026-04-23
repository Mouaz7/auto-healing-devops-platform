"""AI Fix Memory — learns from past pipeline outcomes.

The platform remembers every fix it generated and whether it was:
  - GREEN (auto-merged with high confidence)
  - YELLOW (sent for human review)
  - RED (blocked — confidence too low)
  - approved (human clicked Approve in Slack)
  - rejected (human clicked Reject in Slack)

When the same error type recurs, the LLM prompt is enriched with
relevant past attempts so it can avoid repeating rejected patterns
and replicate successful ones. This is "few-shot learning from history."

Storage: append-only JSONL (same pattern as audit_log.py — no new deps).

Usage:
    from src.shared.fix_memory import fix_memory

    # After pipeline_complete:
    fix_memory.record(error_type, root_cause, affected_files,
                      fix_patch, outcome, confidence, explanation, build_id, pr_url)

    # Before generating a fix:
    past = fix_memory.query(error_type, root_cause, affected_files, limit=3)

    # When human approves/rejects from Slack:
    fix_memory.update_outcome(build_id, approved=True)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_PATH = "/var/log/auto-healer/fix_memory.jsonl"


def _fingerprint(text: str) -> str:
    """Short SHA-256 fingerprint of *text* for similarity grouping."""
    return hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:16]


def _jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard similarity between two file lists (0.0-1.0)."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


class FixMemory:
    """Thread-safe, append-only fix history store.

    Records are kept in a JSONL file so they survive container restarts.
    Queries scan the file in reverse (newest-first) and return the top *limit*
    records that match the error type and have sufficient file similarity.

    Args:
        path: Path to the JSONL memory file.
        min_file_similarity: Minimum Jaccard score to consider a past fix
            relevant. Default 0.0 = any fix for the same error_type qualifies.
    """

    def __init__(self, path: str | None = None, min_file_similarity: float = 0.0) -> None:
        self._path = Path(path or os.getenv("FIX_MEMORY_PATH", _DEFAULT_MEMORY_PATH))
        self._min_sim = min_file_similarity
        self._lock = threading.Lock()
        self._init_file()

    def _init_file(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch(exist_ok=True)
            logger.info("fix_memory_path=%s", self._path)
        except OSError as exc:
            logger.warning("fix_memory_unavailable path=%s error=%s", self._path, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        error_type: str,
        root_cause: str,
        affected_files: list[str],
        fix_patch: str,
        outcome: str,          # "GREEN" | "YELLOW" | "RED"
        confidence: float,
        explanation: str,
        build_id: str,
        pr_url: str = "",
    ) -> None:
        """Persist one fix attempt to the memory store."""
        entry: dict[str, Any] = {
            "ts":                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "build_id":          build_id,
            "error_type":        error_type,
            "root_cause_hash":   _fingerprint(root_cause),
            "root_cause_short":  root_cause[:120],
            "files_key":         ",".join(sorted(affected_files)),
            "fix_hash":          _fingerprint(fix_patch[:500]),
            "fix_preview":       fix_patch[:300],
            "outcome":           outcome,
            "confidence":        round(confidence, 3),
            "explanation":       explanation[:300],
            "pr_url":            pr_url,
            "approved":          None,   # set later by update_outcome()
        }
        self._append(entry)
        logger.info("fix_memory_recorded build_id=%s outcome=%s conf=%.2f",
                    build_id, outcome, confidence)

    def update_outcome(self, build_id: str, approved: bool) -> None:
        """Append an approval/rejection stamp for a previously recorded fix."""
        entry: dict[str, Any] = {
            "ts":       datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "build_id": build_id,
            "_update":  True,
            "approved": approved,
        }
        self._append(entry)
        action = "approved" if approved else "rejected"
        logger.info("fix_memory_outcome build_id=%s action=%s", build_id, action)

    def query(
        self,
        error_type: str,
        root_cause: str,
        affected_files: list[str],
        limit: int = 3,
    ) -> list[dict]:
        """Return up to *limit* relevant past fix records (newest first).

        Matching criteria:
          1. Same error_type (exact)
          2. Jaccard similarity of affected_files >= min_file_similarity
          3. Sorted: GREEN > YELLOW > RED, then by recency

        Each returned dict includes: ts, outcome, confidence, explanation,
        fix_preview, approved, pr_url (safe to inject into a prompt).
        """
        all_records = self._load_records()

        # Merge _update stamps into their parent records
        updates: dict[str, bool | None] = {}
        for rec in all_records:
            if rec.get("_update"):
                updates[rec["build_id"]] = rec.get("approved")

        candidates = []
        for rec in all_records:
            if rec.get("_update"):
                continue
            if rec.get("error_type") != error_type:
                continue
            files = rec.get("files_key", "").split(",") if rec.get("files_key") else []
            sim = _jaccard(affected_files, [f for f in files if f])
            if sim < self._min_sim:
                continue
            rec["approved"] = updates.get(rec["build_id"], rec.get("approved"))
            rec["_sim"] = sim
            candidates.append(rec)

        # Sort: GREEN first, then by similarity, then by recency (newest first)
        _rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
        candidates.sort(
            key=lambda r: (_rank.get(r.get("outcome", "RED"), 2),
                           -r.get("_sim", 0),
                           r.get("ts", "") ),
            reverse=False,
        )
        # Reverse time within same tier: newest first
        result = []
        for r in candidates[:limit]:
            r.pop("_sim", None)
            result.append(r)

        logger.debug("fix_memory_query error_type=%s matches=%d", error_type, len(result))
        return result

    def stats(self) -> dict:
        """Return per-error-type success rates (for /api/stats)."""
        records = self._load_records()
        counts: dict[str, dict[str, int]] = {}
        for rec in records:
            if rec.get("_update"):
                continue
            et = rec.get("error_type", "UNKNOWN")
            if et not in counts:
                counts[et] = {"GREEN": 0, "YELLOW": 0, "RED": 0, "total": 0}
            outcome = rec.get("outcome", "RED")
            counts[et][outcome] = counts[et].get(outcome, 0) + 1
            counts[et]["total"] += 1

        result = {}
        for et, c in counts.items():
            total = c["total"]
            result[et] = {
                "total":       total,
                "green_rate":  round(c["GREEN"] / total, 2) if total else 0,
                "yellow_rate": round(c["YELLOW"] / total, 2) if total else 0,
                "red_rate":    round(c["RED"] / total, 2) if total else 0,
            }
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _append(self, entry: dict) -> None:
        line = json.dumps(entry, default=str) + "\n"
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
        except OSError as exc:
            logger.warning("fix_memory_write_failed error=%s", exc)

    def _load_records(self) -> list[dict]:
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
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return records


def build_memory_context(past_fixes: list[dict], max_chars: int = 800) -> str:
    """Format past fix records into a human-readable prompt section.

    Injected into the Agent 5 prompt so the LLM knows what was tried before
    and whether it succeeded. Capped at *max_chars* to stay within token budget.
    """
    if not past_fixes:
        return ""

    lines = ["Past fix attempts for this error type (use as reference):"]
    for rec in past_fixes:
        approved = rec.get("approved")
        if approved is True:
            human = " ✓ HUMAN APPROVED"
        elif approved is False:
            human = " ✗ HUMAN REJECTED — avoid this approach"
        else:
            human = ""
        outcome = rec.get("outcome", "RED")
        conf = round(rec.get("confidence", 0) * 100)
        ts = rec.get("ts", "")[:10]
        expl = rec.get("explanation", "")[:120]
        lines.append(f"  [{ts}] {outcome} ({conf}%){human}: {expl}")

    context = "\n".join(lines)
    if len(context) > max_chars:
        context = context[:max_chars] + "\n  ... (truncated)"
    return context


# Global singleton
fix_memory = FixMemory()
