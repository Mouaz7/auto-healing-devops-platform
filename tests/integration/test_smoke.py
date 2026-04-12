"""Smoke tests — verify /health on all 7 services.

These tests require docker-compose up --build.
Run with: pytest tests/integration/test_smoke.py -m integration
"""
from __future__ import annotations

import pathlib

import pytest
import httpx


SERVICES = {
    "log_cleaner":    "http://localhost:8081",
    "jenkins":        "http://localhost:8082",
    "gerrit":         "http://localhost:8083",
    "knowledge_graph":"http://localhost:8084",
    "orchestrator":   "http://localhost:8085",
    "llm":            "http://localhost:8086",
    "notification":   "http://localhost:8087",
}


@pytest.mark.integration
@pytest.mark.parametrize("name,base_url", SERVICES.items())
def test_service_health(name: str, base_url: str) -> None:
    """Each service must respond 200 with status=ok on /health."""
    resp = httpx.get(f"{base_url}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.integration
def test_log_cleaner_reduces_logs() -> None:
    """Agent 3 must clean a real log file and reduce it by >50%."""
    fixture = pathlib.Path(
        "tests/fixtures/sample_jenkins_logs/build_failure_import_error.log"
    )
    raw_log = fixture.read_text() if fixture.exists() else (
        "DEBUG init\n" * 100 +
        "ImportError: cannot import name 'Foo'\n"
        '  File "src/app.py", line 3\n'
    )
    resp = httpx.post(
        "http://localhost:8081/tools/clean_logs",
        json={"raw_log": raw_log, "build_id": "smoke-001"},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reduction_pct"] > 50.0
    assert "ImportError" in data["cleaned_logs"]


@pytest.mark.integration
def test_orchestrator_rejects_empty_payload() -> None:
    """Orchestrator /tools/handle_build_failure rejects missing build_id."""
    resp = httpx.post(
        "http://localhost:8085/tools/handle_build_failure",
        json={"raw_log": "some log"},
        timeout=5,
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_all_services_expose_metrics() -> None:
    """Each service must expose /metrics endpoint."""
    for name, base_url in SERVICES.items():
        resp = httpx.get(f"{base_url}/metrics", timeout=5)
        assert resp.status_code == 200, f"{name} /metrics failed"
        assert "auto_healer" in resp.text or "agent_" in resp.text or "#" in resp.text
