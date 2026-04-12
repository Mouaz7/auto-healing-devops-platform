"""Root conftest.py - shared fixtures for all tests."""
import pathlib

import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
SAMPLE_LOGS_DIR = FIXTURES_DIR / "sample_jenkins_logs"


@pytest.fixture
def fixtures_dir() -> pathlib.Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_logs_dir() -> pathlib.Path:
    return SAMPLE_LOGS_DIR


@pytest.fixture
def import_error_log() -> str:
    return (SAMPLE_LOGS_DIR / "build_failure_import_error.log").read_text()


@pytest.fixture
def syntax_error_log() -> str:
    return (SAMPLE_LOGS_DIR / "build_failure_syntax_error.log").read_text()


@pytest.fixture
def success_log() -> str:
    return (SAMPLE_LOGS_DIR / "build_success.log").read_text()
