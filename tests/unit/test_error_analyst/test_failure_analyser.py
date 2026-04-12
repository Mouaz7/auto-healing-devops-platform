from __future__ import annotations

import pytest

from src.knowledge_graph_mcp.failure_analyser import FailureAnalyser, _parse_llm_response
from src.shared.models import BlastRadius, ErrorType


@pytest.fixture
def analyser() -> FailureAnalyser:
    return FailureAnalyser(nim_client=None)


class TestDetectErrorType:
    def test_import_error(self, analyser, cleaned_import_error_log):
        result = analyser.analyse(cleaned_import_error_log, "b1")
        assert result.error_type == ErrorType.IMPORT_ERROR

    def test_module_not_found(self, analyser):
        log = "ModuleNotFoundError: No module named 'requests'\n"
        result = analyser.analyse(log, "b2")
        assert result.error_type == ErrorType.IMPORT_ERROR

    def test_syntax_error(self, analyser, cleaned_syntax_error_log):
        result = analyser.analyse(cleaned_syntax_error_log, "b3")
        assert result.error_type == ErrorType.SYNTAX_ERROR

    def test_type_error(self, analyser):
        log = "TypeError: unsupported operand type(s) for +: 'int' and 'str'\n"
        result = analyser.analyse(log, "b4")
        assert result.error_type == ErrorType.TYPE_ERROR

    def test_assertion_error(self, analyser):
        log = "AssertionError\nFAILED tests/test_main.py::test_something\n"
        result = analyser.analyse(log, "b5")
        assert result.error_type == ErrorType.ASSERTION_ERROR

    def test_file_not_found(self, analyser):
        log = "FileNotFoundError: [Errno 2] No such file or directory: 'config.yml'\n"
        result = analyser.analyse(log, "b6")
        assert result.error_type == ErrorType.FILE_NOT_FOUND

    def test_attribute_error(self, analyser):
        log = "AttributeError: 'NoneType' object has no attribute 'strip'\n"
        result = analyser.analyse(log, "b7")
        assert result.error_type == ErrorType.ATTRIBUTE_ERROR

    def test_unknown_returns_low_confidence(self, analyser):
        log = "Something went wrong, no recognisable pattern\n"
        result = analyser.analyse(log, "b8")
        assert result.error_type == ErrorType.UNKNOWN
        assert result.confidence == pytest.approx(0.3)

    def test_known_error_returns_high_confidence(self, analyser, cleaned_import_error_log):
        result = analyser.analyse(cleaned_import_error_log, "b9")
        assert result.confidence == pytest.approx(0.9)


class TestExtractFiles:
    def test_extracts_file_paths_from_traceback(self, analyser):
        log = (
            'Traceback (most recent call last):\n'
            '  File "app/main.py", line 3, in <module>\n'
            '    from bar import Foo\n'
            '  File "mypackage/bar.py", line 1, in <module>\n'
            'ImportError: cannot import name Foo\n'
        )
        result = analyser.analyse(log, "b10")
        assert "app/main.py" in result.affected_files
        assert "mypackage/bar.py" in result.affected_files

    def test_no_files_in_log(self, analyser):
        log = "TypeError: bad argument\n"
        result = analyser.analyse(log, "b11")
        assert result.affected_files == []

    def test_deduplicates_files(self, analyser):
        log = (
            '  File "app/main.py", line 1\n'
            '  File "app/main.py", line 5\n'
        )
        result = analyser.analyse(log, "b12")
        assert result.affected_files.count("app/main.py") == 1


class TestBlastRadius:
    def test_no_files_is_low(self, analyser):
        result = analyser.analyse("TypeError: bad arg\n", "b13")
        assert result.blast_radius == BlastRadius.LOW

    def test_one_file_is_low(self, analyser):
        log = 'File "src/utils.py", line 1\nTypeError: bad\n'
        result = analyser.analyse(log, "b14")
        assert result.blast_radius == BlastRadius.LOW

    def test_two_files_is_medium(self, analyser):
        log = (
            'File "src/a.py", line 1\n'
            'File "src/b.py", line 1\n'
            'TypeError: bad\n'
        )
        result = analyser.analyse(log, "b15")
        assert result.blast_radius == BlastRadius.MEDIUM

    def test_six_files_is_high(self, analyser):
        lines = "\n".join(f'File "src/file{i}.py", line 1' for i in range(6))
        result = analyser.analyse(lines + "\nTypeError: bad\n", "b16")
        assert result.blast_radius == BlastRadius.HIGH

    def test_critical_path_forces_high(self, analyser):
        log = 'File "tests/test_main.py", line 1\nAssertionError\n'
        result = analyser.analyse(log, "b17")
        assert result.blast_radius == BlastRadius.HIGH

    def test_init_file_forces_high(self, analyser):
        log = 'File "mypackage/__init__.py", line 1\nImportError: bad\n'
        result = analyser.analyse(log, "b18")
        assert result.blast_radius == BlastRadius.HIGH


class TestLlmFallback:
    def test_llm_called_for_unknown_error(self, monkeypatch):
        call_log: list[str] = []

        class FakeNim:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                call_log.append("called")
                return (
                    "ERROR_TYPE: IMPORT_ERROR\n"
                    "ROOT_CAUSE: missing module\n"
                    "AFFECTED_FILES: src/main.py"
                )

        analyser = FailureAnalyser(nim_client=FakeNim())  # type: ignore[arg-type]
        result = analyser.analyse("Unknown build noise\n", "b19")
        assert call_log == ["called"]
        assert result.error_type == ErrorType.IMPORT_ERROR
        assert "src/main.py" in result.affected_files

    def test_llm_not_called_for_known_error(self, monkeypatch):
        call_log: list[str] = []

        class FakeNim:
            def complete(self, messages, max_tokens=None):  # noqa: ARG002
                call_log.append("called")
                return ""

        analyser = FailureAnalyser(nim_client=FakeNim())  # type: ignore[arg-type]
        analyser.analyse("ImportError: bad import\n", "b20")
        assert call_log == []


class TestParseLlmResponse:
    def test_parses_full_response(self):
        response = (
            "ERROR_TYPE: SYNTAX_ERROR\n"
            "ROOT_CAUSE: missing colon after function definition\n"
            "AFFECTED_FILES: src/utils.py, src/main.py"
        )
        error_type, root_cause, files = _parse_llm_response(response)
        assert error_type == ErrorType.SYNTAX_ERROR
        assert root_cause == "missing colon after function definition"
        assert files == ["src/utils.py", "src/main.py"]

    def test_unknown_type_on_bad_value(self):
        response = "ERROR_TYPE: BANANA\nROOT_CAUSE: weird\nAFFECTED_FILES:"
        error_type, _, _ = _parse_llm_response(response)
        assert error_type == ErrorType.UNKNOWN

    def test_empty_response(self):
        error_type, root_cause, files = _parse_llm_response("")
        assert error_type == ErrorType.UNKNOWN
        assert files == []
