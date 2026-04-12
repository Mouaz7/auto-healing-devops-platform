from __future__ import annotations

import json

import pytest

from src.llm_mcp.fix_generator import FixGenerator, FixTooLongError, _parse_response
from src.llm_mcp.prompt_templates import MAX_FIX_LINES, MAX_RETRIES
from src.shared.model_fallback import AllModelsFailed
from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis


@pytest.fixture
def analysis(import_error_analysis) -> FailureAnalysis:
    return import_error_analysis


def _make_nim(responses: list[str]):
    """Fake NimClient that returns responses in sequence."""
    responses = list(responses)

    class FakeNim:
        def complete(self, messages, max_tokens=None):  # noqa: ARG002
            if not responses:
                raise RuntimeError("No more responses")
            return responses.pop(0)

    return FakeNim()


def _json_response(fix_code: str, confidence: float = 0.9) -> str:
    return json.dumps({
        "fix_code": fix_code,
        "confidence": confidence,
        "explanation": "Added missing class",
        "files_to_modify": ["mypackage/bar.py"],
    })


class TestGenerateFix:
    def test_returns_code_fix(self, analysis, safe_fix_code):
        nim = _make_nim([_json_response(safe_fix_code)])
        gen = FixGenerator(nim_client=nim)  # type: ignore[arg-type]
        result = gen.generate_fix(analysis, "class Bar: pass", "ImportError logs")
        assert isinstance(result, CodeFix)
        assert result.fix_patch == safe_fix_code
        assert result.build_id == analysis.build_id

    def test_confidence_from_llm(self, analysis, safe_fix_code):
        nim = _make_nim([_json_response(safe_fix_code, confidence=0.75)])
        gen = FixGenerator(nim_client=nim)  # type: ignore[arg-type]
        result = gen.generate_fix(analysis, "", "logs")
        assert result.confidence == pytest.approx(0.75)

    def test_files_to_modify_defaults_to_affected(self, analysis):
        payload = json.dumps({"fix_code": "x = 1", "confidence": 0.8, "explanation": "fix"})
        nim = _make_nim([payload])
        gen = FixGenerator(nim_client=nim)  # type: ignore[arg-type]
        result = gen.generate_fix(analysis, "", "logs")
        assert result.files_to_modify == analysis.affected_files

    def test_no_nim_raises_runtime_error(self, analysis):
        gen = FixGenerator(nim_client=None)
        with pytest.raises(RuntimeError, match="No NIM client configured"):
            gen.generate_fix(analysis, "", "logs")

    def test_retries_on_failure(self, analysis, safe_fix_code):
        call_count = [0]

        class RetryNim:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                call_count[0] += 1
                if call_count[0] < 2:
                    raise ConnectionError("timeout")
                return _json_response(safe_fix_code)

        gen = FixGenerator(nim_client=RetryNim())  # type: ignore[arg-type]
        result = gen.generate_fix(analysis, "", "logs")
        assert call_count[0] == 2
        assert result.fix_patch == safe_fix_code

    def test_raises_after_max_retries(self, analysis):
        class AlwaysFails:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                raise ConnectionError("always fails")

        gen = FixGenerator(nim_client=AlwaysFails())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="Max retries exhausted"):
            gen.generate_fix(analysis, "", "logs")

    def test_fix_too_long_raises(self, analysis):
        long_code = "\n".join(f"x_{i} = {i}" for i in range(MAX_FIX_LINES + 2))
        nim = _make_nim([_json_response(long_code)])
        gen = FixGenerator(nim_client=nim)  # type: ignore[arg-type]
        with pytest.raises(FixTooLongError):
            gen.generate_fix(analysis, "", "logs")

    def test_all_models_failed_propagates(self, analysis):
        class AllFailed:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                raise AllModelsFailed("no models")

        gen = FixGenerator(nim_client=AllFailed())  # type: ignore[arg-type]
        with pytest.raises(AllModelsFailed):
            gen.generate_fix(analysis, "", "logs")


class TestParseResponse:
    def test_bare_json(self, safe_fix_code):
        raw = _json_response(safe_fix_code)
        parsed = _parse_response(raw)
        assert parsed["fix_code"] == safe_fix_code

    def test_markdown_json_block(self, safe_fix_code):
        raw = f"Here is the fix:\n```json\n{_json_response(safe_fix_code)}\n```"
        parsed = _parse_response(raw)
        assert parsed["fix_code"] == safe_fix_code

    def test_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="Could not parse"):
            _parse_response("not json at all")

    def test_max_retries_constant(self):
        assert MAX_RETRIES == 2

    def test_max_fix_lines_constant(self):
        assert MAX_FIX_LINES == 50
