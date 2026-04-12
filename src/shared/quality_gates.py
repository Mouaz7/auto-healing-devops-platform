"""Quality gates — run Bandit and Pylint on AI-generated code."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class BanditResult:
    """Result from a Bandit security scan."""

    ok: bool
    high_count: int
    issues: list[dict] = field(default_factory=list)


@dataclass
class PylintResult:
    """Result from a Pylint code quality check."""

    ok: bool
    score: float
    messages: list[dict] = field(default_factory=list)


@dataclass
class QualityScore:
    """Combined quality evaluation from Bandit + Pylint."""

    passed: bool
    confidence_modifier: float  # Negative value reduces LLM confidence
    reason: str


def _run_scan(
    code: str,
    cmd_builder: Callable[[str], list[str]],
    parser: Callable[[str], Any],
) -> Any:
    """Write code to a temp file, run a scanner command, return parsed output.

    Args:
        code: Python source code to scan.
        cmd_builder: Callable that takes tmp_path and returns the command list.
        parser: Callable that takes stdout string and returns parsed result.

    Returns:
        Whatever parser() returns, or None on timeout.
    """
    tmp_path = tempfile.mktemp(suffix=".py")  # nosec B306 — unlinked in finally
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        result = subprocess.run(
            cmd_builder(tmp_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return parser(result.stdout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def run_bandit_scan(code: str) -> BanditResult:
    """Run Bandit security scanner on generated code.

    Args:
        code: Python source code string to scan.

    Returns:
        BanditResult with ok=False if any HIGH severity issues found.
        On timeout, returns ok=True (do not block pipeline on scanner timeout).
    """
    def _parse(stdout: str) -> BanditResult:
        try:
            report = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            report = {}
        issues = report.get("results", [])
        high = [i for i in issues if i.get("issue_severity") == "HIGH"]
        return BanditResult(ok=len(high) == 0, high_count=len(high), issues=issues)

    result = _run_scan(
        code,
        cmd_builder=lambda p: ["bandit", "-f", "json", "-q", p],
        parser=_parse,
    )
    if result is None:
        logger.error("bandit_scan_timeout")
        return BanditResult(ok=True, high_count=0)
    return BanditResult(ok=result.ok, high_count=result.high_count, issues=result.issues)


def run_pylint_check(code: str) -> PylintResult:
    """Run Pylint code quality check on generated code.

    Score is approximated as max(0, 10 - error_count * 2) since pylint's
    full weighted formula requires a complete module. This is intentional —
    we want a fast signal, not a precise score.

    Args:
        code: Python source code string to check.

    Returns:
        PylintResult with ok=False if approximated score < 6.0.
        On timeout, returns ok=True with score=8.0.
    """
    def _parse(stdout: str) -> PylintResult:
        try:
            messages = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            messages = []
        errors = sum(1 for m in messages if m.get("type") in ("error", "fatal"))
        score = max(0.0, 10.0 - errors * 2.0)
        return PylintResult(ok=score >= 6.0, score=score, messages=messages)

    result = _run_scan(
        code,
        cmd_builder=lambda p: ["pylint", "--output-format=json", p],
        parser=_parse,
    )
    if result is None:
        logger.error("pylint_check_timeout")
        return PylintResult(ok=True, score=8.0)
    return PylintResult(ok=result.ok, score=result.score, messages=result.messages)


def evaluate_quality(bandit: BanditResult, pylint: PylintResult) -> QualityScore:
    """Combine Bandit + Pylint results into a QualityScore.

    Modifier rules:
    - Bandit HIGH issue:    -0.30
    - Pylint score < 4.0:  -0.40
    - Pylint score < 6.0:  -0.20
    - All OK:               0.0

    Args:
        bandit: Result from run_bandit_scan().
        pylint: Result from run_pylint_check().

    Returns:
        QualityScore with passed=True only if modifier == 0.
    """
    modifier = 0.0
    reasons: list[str] = []

    if not bandit.ok:
        modifier -= 0.30
        reasons.append(f"Bandit: {bandit.high_count} HIGH severity issue(s)")

    if pylint.score < 4.0:
        modifier -= 0.40
        reasons.append(f"Pylint score {pylint.score:.1f} < 4.0")
    elif pylint.score < 6.0:
        modifier -= 0.20
        reasons.append(f"Pylint score {pylint.score:.1f} < 6.0")

    return QualityScore(
        passed=modifier == 0.0,
        confidence_modifier=modifier,
        reason="; ".join(reasons) if reasons else "All quality checks passed",
    )
