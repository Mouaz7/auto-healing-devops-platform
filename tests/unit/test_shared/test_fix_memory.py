"""Unit tests for src.shared.fix_memory."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.shared.fix_memory import FixMemory, build_memory_context


@pytest.fixture
def mem(tmp_path):
    """FixMemory instance backed by a temp file."""
    return FixMemory(path=str(tmp_path / "fix_memory.jsonl"))


class TestFixMemoryRecord:
    def test_record_creates_file(self, mem, tmp_path):
        mem.record("ASSERTION_ERROR", "wrong value", ["tests/t.py"],
                   "assert 1 == 1", "GREEN", 0.9, "fixed", "b-001")
        files = list((tmp_path).iterdir())
        assert any(f.suffix == ".jsonl" for f in files)

    def test_record_multiple_entries(self, mem):
        for i in range(3):
            mem.record("ASSERTION_ERROR", "cause", ["t.py"],
                       "fix", "GREEN", 0.9, "ok", f"b-{i:03d}")
        records = mem._load_records()
        assert len(records) == 3

    def test_update_outcome_appends_stamp(self, mem):
        mem.record("ASSERTION_ERROR", "cause", ["t.py"], "fix", "GREEN", 0.9, "ok", "b-001")
        mem.update_outcome("b-001", approved=True)
        records = mem._load_records()
        assert len(records) == 2
        assert records[-1].get("_update") is True
        assert records[-1]["approved"] is True


class TestFixMemoryQuery:
    def test_query_returns_matching_records(self, mem):
        mem.record("ASSERTION_ERROR", "cause", ["tests/t.py"],
                   "fix", "GREEN", 0.9, "ok", "b-001")
        results = mem.query("ASSERTION_ERROR", "cause", ["tests/t.py"])
        assert len(results) == 1

    def test_query_excludes_different_error_type(self, mem):
        mem.record("IMPORT_ERROR", "missing", ["src/a.py"],
                   "fix", "GREEN", 0.9, "ok", "b-002")
        results = mem.query("ASSERTION_ERROR", "cause", ["src/a.py"])
        assert results == []

    def test_query_merges_approved_stamp(self, mem):
        mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "GREEN", 0.9, "ok", "b-001")
        mem.update_outcome("b-001", approved=True)
        results = mem.query("ASSERTION_ERROR", "c", ["t.py"])
        assert results[0]["approved"] is True

    def test_query_respects_limit(self, mem):
        for i in range(5):
            mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "GREEN", 0.9, "ok", f"b-{i:03d}")
        results = mem.query("ASSERTION_ERROR", "c", ["t.py"], limit=2)
        assert len(results) <= 2

    def test_query_green_sorted_first(self, mem):
        mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "RED",   0.3, "bad", "b-001")
        mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "GREEN", 0.9, "good", "b-002")
        results = mem.query("ASSERTION_ERROR", "c", ["t.py"], limit=2)
        assert results[0]["outcome"] == "GREEN"

    def test_query_empty_memory_returns_empty(self, mem):
        results = mem.query("ASSERTION_ERROR", "c", ["t.py"])
        assert results == []


class TestFixMemoryStats:
    def test_stats_counts_outcomes(self, mem):
        mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "GREEN",  0.9, "ok", "b-001")
        mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "YELLOW", 0.7, "ok", "b-002")
        mem.record("ASSERTION_ERROR", "c", ["t.py"], "fix", "RED",    0.3, "bad", "b-003")
        stats = mem.stats()
        assert "ASSERTION_ERROR" in stats
        et = stats["ASSERTION_ERROR"]
        assert et["total"] == 3
        assert et["green_rate"] == pytest.approx(1/3, abs=0.01)
        assert et["yellow_rate"] == pytest.approx(1/3, abs=0.01)
        assert et["red_rate"] == pytest.approx(1/3, abs=0.01)

    def test_stats_empty_returns_empty(self, mem):
        assert mem.stats() == {}


class TestBuildMemoryContext:
    def test_empty_past_returns_empty_string(self):
        assert build_memory_context([]) == ""

    def test_format_includes_outcome_and_confidence(self):
        rec = {
            "ts": "2026-04-20T12:00:00+00:00",
            "outcome": "GREEN",
            "confidence": 0.91,
            "explanation": "Fixed assertion",
            "approved": None,
        }
        ctx = build_memory_context([rec])
        assert "GREEN" in ctx
        assert "91%" in ctx
        assert "Fixed assertion" in ctx

    def test_approved_shows_checkmark(self):
        rec = {"ts": "2026-04-20", "outcome": "GREEN",
               "confidence": 0.9, "explanation": "ok", "approved": True}
        ctx = build_memory_context([rec])
        assert "HUMAN APPROVED" in ctx

    def test_rejected_shows_warning(self):
        rec = {"ts": "2026-04-20", "outcome": "YELLOW",
               "confidence": 0.7, "explanation": "ok", "approved": False}
        ctx = build_memory_context([rec])
        assert "HUMAN REJECTED" in ctx

    def test_truncated_at_max_chars(self):
        recs = [
            {"ts": "2026-04-20", "outcome": "GREEN", "confidence": 0.9,
             "explanation": "x" * 200, "approved": None}
        ] * 10
        ctx = build_memory_context(recs, max_chars=100)
        assert len(ctx) <= 130  # slight overflow for "... (truncated)"
        assert "truncated" in ctx
