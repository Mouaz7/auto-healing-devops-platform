"""Runtime quality checks for LLM-generated code patches.

Runs bandit (security) and pylint (style/errors) on code before it is
submitted as a fix. Uses the same pattern as src/shared/quality_gates.py
to avoid TOCTOU and unbound-variable issues.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile


def run_bandit_scan(code: str) -> dict:
    """Run bandit on *code*. Returns ``{ok, issues, high_count}``.

    A result is considered ``ok`` when there are zero HIGH-severity findings.
    """
    tmp_path = tempfile.mktemp(suffix=".py")  # nosec B306 — deleted in finally
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        result = subprocess.run(
            ["bandit", "-f", "json", tmp_path],
            capture_output=True, text=True, timeout=30,
            check=False,
        )
        try:
            report = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError:
            report = {}
        issues = report.get("results", [])
        high_issues = [i for i in issues if i.get("issue_severity") == "HIGH"]
        return {"ok": len(high_issues) == 0, "issues": issues, "high_count": len(high_issues)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def run_pylint_check(code: str) -> dict:
    """Run pylint on *code*. Returns ``{ok, score, messages}``.

    Score < 6.0 is considered a failure (``ok=False``).
    """
    tmp_path = tempfile.mktemp(suffix=".py")  # nosec B306
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        result = subprocess.run(
            ["pylint", "--output-format=json", tmp_path],
            capture_output=True, text=True, timeout=30,
            check=False,
        )
        try:
            messages = json.loads(result.stdout) if result.stdout else []
        except json.JSONDecodeError:
            messages = []
        error_count = sum(1 for m in messages if m.get("type") in ("error", "fatal"))
        score = max(0.0, 10.0 - error_count * 2.0)
        return {"ok": score >= 6.0, "score": score, "messages": messages}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
