from __future__ import annotations

from datetime import datetime

import pytest

from src.shared.models import (
    BlastRadius,
    BuildEvent,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TrafficLightColour,
    TrafficLightResult,
)


@pytest.fixture
def build_event() -> BuildEvent:
    return BuildEvent(
        build_id="test-001",
        repo="example/app",
        branch="main",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        job_name="example-app-ci",
        status="FAILED",
        log_url="http://jenkins/job/1",
    )


@pytest.fixture
def failure_analysis() -> FailureAnalysis:
    return FailureAnalysis(
        build_id="test-001",
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=BlastRadius.LOW,
        affected_files=["mypackage/bar.py"],
        confidence=0.90,
        root_cause="Missing export in mypackage.bar",
        stack_trace="ImportError: cannot import name Foo",
    )


@pytest.fixture
def code_fix() -> CodeFix:
    return CodeFix(
        build_id="test-001",
        fix_patch="--- a/mypackage/bar.py\n+++ b/mypackage/bar.py\n@@ -0,0 +1,2 @@\n+class Foo:\n+    pass\n",
        files_to_modify=["mypackage/bar.py"],
        confidence=0.88,
        explanation="Added missing Foo class",
        lint_ok=True,
        test_ok=False,
    )


@pytest.fixture
def traffic_light_green() -> TrafficLightResult:
    return TrafficLightResult(
        build_id="test-001",
        colour=TrafficLightColour.GREEN,
        final_score=0.90,
        auto_merge_allowed=True,
        reason="High confidence, low blast radius",
        blast_radius=BlastRadius.LOW,
    )


@pytest.fixture
def traffic_light_red() -> TrafficLightResult:
    return TrafficLightResult(
        build_id="test-001",
        colour=TrafficLightColour.RED,
        final_score=0.45,
        auto_merge_allowed=False,
        reason="Low confidence",
        blast_radius=BlastRadius.LOW,
    )
