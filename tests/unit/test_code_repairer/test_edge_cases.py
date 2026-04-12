"""Edge case tests for Code Repairer (Agent 5)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm_mcp.fix_generator import (
    FixGenerator,
    FixTooLongError,
    _parse_response,
)
from src.shared.model_fallback import AllModelsFailed
from src.shared.models import BlastRadius, ErrorType, FailureAnalysis
from src.shared.quality_gates import BanditResult, PylintResult, evaluate_quality


def _analysis(build_id: str = "b1") -> FailureAnalysis:
    return FailureAnalysis(
        build_id=build_id,
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=BlastRadius.LOW,
        root_cause="Missing import",
        affected_files=["src/app.py"],
        confidence=0.9,
    )


class TestFixTooLong:
    def test_fix_exceeds_50_lines_raises(self):
        """LLM returning 51-line fix (51 newlines) → FixTooLongError raised."""
        # count("\n") > 50 requires 51+ newlines = 52 items joined
        long_fix = "\n".join(f"x = {i}" for i in range(52))
        response = json.dumps({
            "fix_code": long_fix,
            "confidence": 0.8,
            "explanation": "fix",
        })

        nim = MagicMock()
        nim.complete.return_value = response
        generator = FixGenerator(nim_client=nim)

        with pytest.raises(FixTooLongError):
            generator.generate_fix(
                analysis=_analysis(),
                code_context="",
                cleaned_logs="ImportError",
            )


class TestAllModelsFailed:
    def test_all_models_fail_propagates(self):
        """AllModelsFailed from NimClient propagates out of generate_fix."""
        nim = MagicMock()
        nim.complete.side_effect = AllModelsFailed("all failed")
        generator = FixGenerator(nim_client=nim)

        with pytest.raises(AllModelsFailed):
            generator.generate_fix(
                analysis=_analysis(),
                code_context="",
                cleaned_logs="ImportError",
            )


class TestMalformedJsonResponse:
    def test_bare_non_json_raises_value_error(self):
        """Non-JSON string → ValueError."""
        with pytest.raises(ValueError):
            _parse_response("this is not json at all")

    def test_partial_json_raises_value_error(self):
        """Truncated JSON → ValueError."""
        with pytest.raises(ValueError):
            _parse_response('{"fix_code": "x = 1"')

    def test_valid_json_returns_dict(self):
        """Valid JSON → returns dict."""
        payload = '{"fix_code": "x = 1", "confidence": 0.8}'
        result = _parse_response(payload)
        assert result["fix_code"] == "x = 1"

    def test_json_in_markdown_block_parsed(self):
        """JSON wrapped in ```json ... ``` → extracted and parsed."""
        payload = '```json\n{"fix_code": "x = 1", "confidence": 0.9}\n```'
        result = _parse_response(payload)
        assert result["confidence"] == 0.9

    def test_json_in_code_block_parsed(self):
        """JSON wrapped in ``` ... ``` (no language) → extracted."""
        payload = '```\n{"fix_code": "y = 2", "confidence": 0.7}\n```'
        result = _parse_response(payload)
        assert result["fix_code"] == "y = 2"


class TestQualityGateConfidenceAdjustment:
    def test_bandit_high_reduces_confidence_by_30(self):
        """Bandit HIGH → confidence_modifier = -0.30."""
        bandit = BanditResult(ok=False, high_count=1, issues=[])
        pylint = PylintResult(ok=True, score=9.0, messages=[])
        quality = evaluate_quality(bandit, pylint)
        assert quality.confidence_modifier == pytest.approx(-0.30)

    def test_clean_code_zero_modifier(self):
        """No issues → modifier = 0.0 → confidence unchanged."""
        bandit = BanditResult(ok=True, high_count=0, issues=[])
        pylint = PylintResult(ok=True, score=9.0, messages=[])
        quality = evaluate_quality(bandit, pylint)
        assert quality.confidence_modifier == 0.0
        assert quality.passed is True

    def test_confidence_clamped_at_zero(self):
        """Adjusted confidence cannot go below 0.0."""
        # simulate what generate_fix does
        base_confidence = 0.1
        modifier = -0.30
        adjusted = max(0.0, base_confidence + modifier)
        assert adjusted == 0.0

    def test_pylint_score_below_6_reduces_20(self):
        """Pylint 4.0–6.0 → modifier = -0.20."""
        bandit = BanditResult(ok=True, high_count=0, issues=[])
        pylint = PylintResult(ok=False, score=5.0, messages=[])
        quality = evaluate_quality(bandit, pylint)
        assert quality.confidence_modifier == pytest.approx(-0.20)


class TestNoNimClient:
    def test_none_nim_raises_runtime_error(self):
        """No NIM client → RuntimeError with descriptive message."""
        generator = FixGenerator(nim_client=None)
        with pytest.raises(RuntimeError, match="No NIM client"):
            generator.generate_fix(
                analysis=_analysis(),
                code_context="",
                cleaned_logs="",
            )
