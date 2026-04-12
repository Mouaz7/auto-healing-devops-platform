from __future__ import annotations

import pytest
from src.shared.models import FailureAnalysis, ErrorType, BlastRadius


@pytest.fixture
def import_error_analysis():
    return FailureAnalysis(
        build_id="test-001",
        error_type=ErrorType.IMPORT_ERROR,
        root_cause="Missing Foo class in mypackage.bar",
        affected_files=["mypackage/bar.py"],
        blast_radius=BlastRadius.LOW,
        confidence=0.88,
    )


@pytest.fixture
def original_file_content():
    return (
        "from __future__ import annotations\n"
        "\n"
        "class Bar:\n"
        "    pass\n"
    )


@pytest.fixture
def safe_fix_code():
    return (
        "from __future__ import annotations\n"
        "\n"
        "class Bar:\n"
        "    pass\n"
        "\n"
        "class Foo:\n"
        "    pass\n"
    )
