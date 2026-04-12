from __future__ import annotations

import pytest


@pytest.fixture
def cleaned_import_error_log():
    return (
        "ImportError: cannot import name Foo from mypackage.bar\n"
        "Traceback (most recent call last):\n"
        "  File app/main.py, line 3\n"
        "    from mypackage.bar import Foo\n"
        "ImportError: cannot import name Foo\n"
    )


@pytest.fixture
def cleaned_syntax_error_log():
    return (
        "SyntaxError: invalid syntax\n"
        "  File app/utils.py, line 42\n"
        "    def broken_func(\n"
        "SyntaxError: invalid syntax\n"
    )


@pytest.fixture
def repo_file_tree():
    return [
        "app/__init__.py",
        "app/main.py",
        "mypackage/__init__.py",
        "mypackage/bar.py",
        "mypackage/utils.py",
        "tests/test_main.py",
    ]
