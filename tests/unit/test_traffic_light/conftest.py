from __future__ import annotations

import pytest
from src.shared.models import BlastRadius


@pytest.fixture
def low_blast_high_confidence():
    return {"llm_confidence": 0.95, "blast_radius": BlastRadius.LOW}


@pytest.fixture
def medium_blast_medium_confidence():
    return {"llm_confidence": 0.70, "blast_radius": BlastRadius.MEDIUM}


@pytest.fixture
def high_blast_high_confidence():
    # HIGH blast radius always forces RED regardless of confidence
    return {"llm_confidence": 0.99, "blast_radius": BlastRadius.HIGH}


@pytest.fixture
def low_blast_low_confidence():
    return {"llm_confidence": 0.30, "blast_radius": BlastRadius.LOW}
