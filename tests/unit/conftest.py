from __future__ import annotations

import pytest


@pytest.fixture
def sample_build_id():
    return "build-test-001"


@pytest.fixture
def sample_repo():
    return "example/my-python-app"


@pytest.fixture
def sample_branch():
    return "main"


@pytest.fixture
def import_error_log():
    return (
        "ERROR: ImportError: cannot import name Foo\n"
        "Traceback (most recent call last):\n"
        "  File app/main.py, line 3\n"
        "    from mypackage.bar import Foo\n"
        "ImportError: cannot import name Foo\n"
    )


@pytest.fixture
def syntax_error_log():
    return (
        "ERROR: SyntaxError: invalid syntax\n"
        "  File app/utils.py, line 42\n"
        "    def broken_func(\n"
        "SyntaxError: invalid syntax\n"
    )


@pytest.fixture
def clean_log():
    return "[INFO] Build started\n[INFO] All tests passed\n[INFO] Build SUCCESS\n"


@pytest.fixture
def noisy_log():
    return (
        "\x1b[32m[INFO]\x1b[0m Download 45%\n"
        "2024-01-15T10:00:00.123Z [INFO] Starting build\n"
        "Download 45%\nDownload 46%\n"
        "ERROR: ImportError: cannot import name Config\n"
        "Traceback (most recent call last):\n"
        "  File main.py, line 1\n"
        "ImportError: cannot import name Config\n"
    )
