from __future__ import annotations

import pytest


@pytest.fixture
def ansi_log():
    return "\x1b[32m[INFO]\x1b[0m \x1b[31mERROR\x1b[0m: ImportError\n"


@pytest.fixture
def timestamped_log():
    return (
        "2024-01-15T10:00:00.123Z [INFO] Build started\n"
        "2024-01-15T10:00:01.456Z [ERROR] ImportError: cannot import name Foo\n"
    )


@pytest.fixture
def noisy_log():
    return (
        "Download 12%\nDownload 13%\n"
        "Progress: [=====     ] 50%\n"
        "\n\n"
        "ERROR: ImportError: cannot import name Foo\n"
        "Traceback (most recent call last):\n"
        "  File main.py, line 1\n"
        "ImportError: cannot import name Foo\n"
    )


@pytest.fixture
def duplicate_log():
    return (
        "ERROR: ImportError\n"
        "ERROR: ImportError\n"
        "ERROR: ImportError\n"
        "Traceback (most recent call last):\n"
    )
