"""Agent 4: Error Analyst — failure analysis via regex + optional NIM LLM.

Regex patterns run first for speed. If confidence is low (UNKNOWN error type),
the NIM LLM chain (thinking models) performs deep root-cause reasoning.
"""
from __future__ import annotations

import re

from src.knowledge_graph_mcp.dependency_tracker import DependencyTracker
from src.shared.models import ErrorType, FailureAnalysis
from src.shared.nim_client import NimClient, SlotParams

# Per-slot params for thinking/reasoning models (higher temp for chain-of-thought)
_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (0.6, 0.7, 4096),
    "FALLBACK_1": (0.2, 0.7, 8192),
    "FALLBACK_2": (1.0, 0.95, 8192),
    "FALLBACK_3": (1.0, 1.0, 16384),
}

_LLM_SYSTEM_PROMPT = (
    "You are a build failure analysis expert. "
    "Given cleaned build logs, identify:\n"
    "1. The exact error type (IMPORT_ERROR, SYNTAX_ERROR, TYPE_ERROR, "
    "ASSERTION_ERROR, FILE_NOT_FOUND, ATTRIBUTE_ERROR, or UNKNOWN)\n"
    "2. The root cause in one sentence\n"
    "3. All affected file paths\n\n"
    "Respond in this exact format:\n"
    "ERROR_TYPE: <type>\n"
    "ROOT_CAUSE: <sentence>\n"
    "AFFECTED_FILES: <file1>, <file2>"
)

# Regex patterns ordered by specificity
ERROR_PATTERNS: dict[ErrorType, list[re.Pattern[str]]] = {
    ErrorType.IMPORT_ERROR: [
        re.compile(r"ImportError:?\s*(.*)", re.IGNORECASE),
        re.compile(r"ModuleNotFoundError:?\s*(.*)", re.IGNORECASE),
        re.compile(r"cannot import name '([^']+)'", re.IGNORECASE),
    ],
    ErrorType.SYNTAX_ERROR: [
        re.compile(r"SyntaxError:?\s*(.*)", re.IGNORECASE),
        re.compile(r"invalid syntax", re.IGNORECASE),
    ],
    ErrorType.TYPE_ERROR: [
        re.compile(r"TypeError:?\s*(.*)", re.IGNORECASE),
    ],
    ErrorType.ASSERTION_ERROR: [
        re.compile(r"AssertionError", re.IGNORECASE),
        re.compile(r"FAILED\s+tests/", re.IGNORECASE),
    ],
    ErrorType.FILE_NOT_FOUND: [
        re.compile(r"FileNotFoundError:?\s*(.*)", re.IGNORECASE),
        re.compile(r"No such file or directory", re.IGNORECASE),
    ],
    ErrorType.ATTRIBUTE_ERROR: [
        re.compile(r"AttributeError:?\s*(.*)", re.IGNORECASE),
    ],
}

# File paths from Python tracebacks: File "path/to/file.py", line N
_FILE_PATH_RE = re.compile(r'File "([^"]+)", line \d+')

# File paths from pytest output: FAILED tests/foo.py::test_bar or ERROR tests/foo.py
_PYTEST_FILE_RE = re.compile(r'(?:FAILED|ERROR)\s+([\w./][^\s:]+\.py)', re.IGNORECASE)

# File paths from our workflow format: FAILED_FILE: ./path/to/file.py
_WORKFLOW_FILE_RE = re.compile(r'FAILED_FILE:\s*([\w./][^\s]+\.py)')


class FailureAnalyser:
    """Analyse cleaned build logs to produce a :class:`FailureAnalysis`.

    Args:
        nim_client: Optional NimClient for deep LLM analysis when regex
            fails to identify the error type. Pass ``None`` in tests.
    """

    def __init__(self, nim_client: NimClient | None = None) -> None:
        self._nim = nim_client
        self._tracker = DependencyTracker()

    def analyse(self, cleaned_logs: str, build_id: str) -> FailureAnalysis:
        """Analyse *cleaned_logs* and return a :class:`FailureAnalysis`."""
        error_type = self._detect_error_type(cleaned_logs)
        affected_files = self._extract_files(cleaned_logs)
        stack_trace = self._extract_stack_trace(cleaned_logs)
        root_cause = self._extract_root_cause(cleaned_logs, error_type)

        # LLM fallback for UNKNOWN errors when a client is available
        if error_type == ErrorType.UNKNOWN and self._nim is not None:
            error_type, root_cause, llm_files = self._llm_analyse(cleaned_logs)
            if llm_files:
                # Merge without duplicates, preserving regex-found files first
                seen = set(affected_files)
                for f in llm_files:
                    if f not in seen:
                        affected_files.append(f)
                        seen.add(f)

        blast_radius = self._tracker.calculate_blast_radius(affected_files)
        confidence = 0.9 if error_type != ErrorType.UNKNOWN else 0.3

        return FailureAnalysis(
            build_id=build_id,
            error_type=error_type,
            blast_radius=blast_radius,
            affected_files=affected_files,
            confidence=confidence,
            root_cause=root_cause,
            stack_trace=stack_trace,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_error_type(self, logs: str) -> ErrorType:
        for error_type, patterns in ERROR_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(logs):
                    return error_type
        return ErrorType.UNKNOWN

    def _extract_files(self, logs: str) -> list[str]:
        """Extract unique file paths from tracebacks, pytest output, and workflow format."""
        seen: dict[str, None] = {}
        # Highest priority: our workflow's explicit FAILED_FILE: marker
        for m in _WORKFLOW_FILE_RE.finditer(logs):
            path = m.group(1).lstrip("./")
            seen[path] = None
        for m in _FILE_PATH_RE.finditer(logs):
            seen[m.group(1)] = None
        for m in _PYTEST_FILE_RE.finditer(logs):
            seen[m.group(1)] = None
        return list(seen)

    def _extract_stack_trace(self, logs: str) -> str:
        """Return lines from first traceback/error block onwards."""
        lines = logs.splitlines()
        result: list[str] = []
        capturing = False
        for line in lines:
            if not capturing and re.search(r"Traceback|Error:|FAILED", line):
                capturing = True
            if capturing:
                result.append(line)
        return "\n".join(result)

    def _extract_root_cause(self, logs: str, error_type: ErrorType) -> str:
        """Return the first matched error message for the detected type."""
        for pattern in ERROR_PATTERNS.get(error_type, []):
            match = pattern.search(logs)
            if match:
                return match.group(0).strip()
        return "Unknown root cause"

    def _llm_analyse(self, logs: str) -> tuple[ErrorType, str, list[str]]:
        """Use NIM LLM to identify error type, root cause, and files."""
        messages = [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": logs[:6000]},
        ]
        if self._nim is None:
            return ErrorType.UNKNOWN, "Unknown root cause", []
        try:
            response = self._nim.complete(messages)
            return _parse_llm_response(response)
        except Exception:  # pylint: disable=broad-exception-caught
            return ErrorType.UNKNOWN, "Unknown root cause", []


def _parse_llm_response(response: str) -> tuple[ErrorType, str, list[str]]:
    """Parse structured LLM response into (error_type, root_cause, files)."""
    error_type = ErrorType.UNKNOWN
    root_cause = "Unknown root cause"
    files: list[str] = []

    for line in response.splitlines():
        if line.startswith("ERROR_TYPE:"):
            raw = line.split(":", 1)[1].strip().upper()
            try:
                error_type = ErrorType(raw)
            except ValueError:
                pass
        elif line.startswith("ROOT_CAUSE:"):
            root_cause = line.split(":", 1)[1].strip()
        elif line.startswith("AFFECTED_FILES:"):
            raw_files = line.split(":", 1)[1].strip()
            files = [f.strip() for f in raw_files.split(",") if f.strip()]

    return error_type, root_cause, files


def make_analyser(env_prefix: str = "ERROR_ANALYST") -> FailureAnalyser:
    """Construct a :class:`FailureAnalyser` wired to the NIM API."""
    nim = NimClient(
        agent_name="error_analyst",
        agent_env_prefix=env_prefix,
        slot_params=_SLOT_PARAMS,
    )
    return FailureAnalyser(nim_client=nim)
