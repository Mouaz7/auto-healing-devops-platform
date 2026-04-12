"""Load test: verify the pipeline handles 3 concurrent builds.

Requires docker-compose services to be running.
Run with: pytest tests/integration/test_load.py -m integration
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

ORCHESTRATOR = "http://localhost:8085"


async def run_single_pipeline(build_id: str) -> dict:
    """Submit one build-failure payload and return the JSON response."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{ORCHESTRATOR}/tools/handle_build_failure",
            json={
                "build_id":  build_id,
                "repo":      "example/app",
                "branch":    "main",
                "scenario":  "A",
                "raw_log":   "Error: ImportError: cannot import name 'Foo'",
            },
        )
    return dict(resp.json())


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_three_concurrent_pipelines() -> None:
    """Max 3 samtida pipelines (GLOBAL_MAX_CONCURRENT_PIPELINES = 3).

    All three builds must complete and return a valid traffic-light status.
    """
    results = await asyncio.gather(
        run_single_pipeline("load-001"),
        run_single_pipeline("load-002"),
        run_single_pipeline("load-003"),
    )
    for result in results:
        assert "build_id" in result, f"Missing build_id in {result}"
        assert result.get("status") in ("GREEN", "YELLOW", "RED"), (
            f"Unexpected status in {result}"
        )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sequential_builds_share_no_state() -> None:
    """Two sequential builds with the same build_id must each complete independently."""
    first  = await run_single_pipeline("load-seq-001")
    second = await run_single_pipeline("load-seq-001")
    assert first.get("build_id")  == "load-seq-001"
    assert second.get("build_id") == "load-seq-001"
