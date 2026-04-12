from __future__ import annotations

import pytest

from src.log_cleaner_mcp.pipeline import LogCleaningPipeline, MIN_REDUCTION_TARGET


@pytest.fixture
def pipeline_no_llm() -> LogCleaningPipeline:
    """Pipeline with LLM disabled — regex only."""
    return LogCleaningPipeline(nim_client=None)


@pytest.fixture
def noisy_build_log() -> str:
    return (
        "2024-01-15T10:00:00Z DEBUG init\n"
        "2024-01-15T10:00:01Z DEBUG load config\n"
        "2024-01-15T10:00:02Z DEBUG connect db\n"
        "2024-01-15T10:00:03Z DEBUG check schema\n"
        "\n"
        "2024-01-15T10:00:04Z INFO  Build started\n"
        "\n"
        "2024-01-15T10:00:05Z ERROR ImportError: cannot import name Foo from bar\n"
        "Traceback (most recent call last):\n"
        '  File "main.py", line 3, in <module>\n'
        "    from bar import Foo\n"
        "ImportError: cannot import name Foo\n"
    )


class TestPipelineNoLlm:
    def test_returns_clean_result(self, pipeline_no_llm, noisy_build_log):
        result = pipeline_no_llm.clean(noisy_build_log)
        assert result.original_lines > 0
        assert result.cleaned_lines <= result.original_lines

    def test_used_llm_false(self, pipeline_no_llm, noisy_build_log):
        result = pipeline_no_llm.clean(noisy_build_log)
        assert result.used_llm is False

    def test_removes_debug_lines(self, pipeline_no_llm, noisy_build_log):
        result = pipeline_no_llm.clean(noisy_build_log)
        assert "DEBUG" not in result.cleaned_text

    def test_removes_timestamps(self, pipeline_no_llm, noisy_build_log):
        result = pipeline_no_llm.clean(noisy_build_log)
        assert "2024-01-15" not in result.cleaned_text

    def test_reduction_ratio_valid(self, pipeline_no_llm, noisy_build_log):
        result = pipeline_no_llm.clean(noisy_build_log)
        assert 0.0 <= result.reduction_ratio <= 1.0

    def test_empty_log(self, pipeline_no_llm):
        result = pipeline_no_llm.clean("")
        assert result.original_lines == 0
        assert result.reduction_ratio == 1.0

    def test_llm_not_called_when_disabled(self, pipeline_no_llm):
        # Even if reduction < MIN_REDUCTION_TARGET, LLM is not called
        tiny = "single error line\n"
        result = pipeline_no_llm.clean(tiny)
        assert result.used_llm is False


class TestPipelineWithLlmFallback:
    def test_calls_llm_when_reduction_below_target(self, monkeypatch):
        """When regex achieves <MIN_REDUCTION_TARGET, LLM should be invoked."""
        call_log: list[str] = []

        class FakeNim:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                call_log.append("called")
                return "LLM cleaned line\n"

        pipeline = LogCleaningPipeline(nim_client=FakeNim())  # type: ignore[arg-type]
        # A log where regex will NOT achieve ≥50% reduction (all non-noisy lines)
        dense_log = "\n".join(f"ERROR real error line {i}" for i in range(10)) + "\n"
        result = pipeline.clean(dense_log)

        assert result.used_llm is True
        assert call_log == ["called"]
        assert "LLM cleaned line" in result.cleaned_text

    def test_no_llm_call_when_regex_sufficient(self, monkeypatch):
        """When regex achieves ≥MIN_REDUCTION_TARGET, LLM should NOT be invoked."""
        call_log: list[str] = []

        class FakeNim:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                call_log.append("called")
                return "LLM output"

        pipeline = LogCleaningPipeline(nim_client=FakeNim())  # type: ignore[arg-type]
        # Lots of debug lines → regex will remove most → high reduction
        noisy = "\n".join(f"DEBUG noise line {i}" for i in range(100)) + "\nERROR real\n"
        result = pipeline.clean(noisy)

        assert result.used_llm is False
        assert call_log == []
