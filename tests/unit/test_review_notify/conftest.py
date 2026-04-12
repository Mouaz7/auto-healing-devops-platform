from __future__ import annotations

import pytest

from src.shared.models import (
    BlastRadius,
    CodeFix,
    ErrorType,
    FailureAnalysis,
    TrafficLightColour,
    TrafficLightResult,
)


@pytest.fixture
def green_result():
    return TrafficLightResult(
        build_id="test-001",
        colour=TrafficLightColour.GREEN,
        final_score=0.92,
        auto_merge_allowed=True,
        reason="High confidence, 1 file, no security issues",
        blast_radius=BlastRadius.LOW,
    )


@pytest.fixture
def yellow_result():
    return TrafficLightResult(
        build_id="test-001",
        colour=TrafficLightColour.YELLOW,
        final_score=0.72,
        auto_merge_allowed=False,
        reason="Medium confidence",
        blast_radius=BlastRadius.MEDIUM,
    )


@pytest.fixture
def red_result():
    return TrafficLightResult(
        build_id="test-001",
        colour=TrafficLightColour.RED,
        final_score=0.20,
        auto_merge_allowed=False,
        reason="HIGH blast radius safety override",
        blast_radius=BlastRadius.HIGH,
        safety_override=True,
    )


@pytest.fixture
def low_analysis():
    return FailureAnalysis(
        build_id="test-001",
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=BlastRadius.LOW,
        confidence=0.9,
        root_cause="Missing class",
    )


@pytest.fixture
def high_analysis():
    return FailureAnalysis(
        build_id="test-001",
        error_type=ErrorType.IMPORT_ERROR,
        blast_radius=BlastRadius.HIGH,
        confidence=0.9,
        root_cause="Critical path affected",
    )


@pytest.fixture
def good_fix():
    return CodeFix(
        build_id="test-001",
        fix_patch="class Foo: pass",
        confidence=0.95,
        explanation="Added missing class",
    )


@pytest.fixture
def weak_fix():
    return CodeFix(
        build_id="test-001",
        fix_patch="# fix",
        confidence=0.45,
        explanation="Uncertain fix",
    )
