#!/usr/bin/env python3
"""
Demo script for the Auto-Healing AI DevOps Platform.

Runs all 6 agents through the full pipeline.
Requires: docker-compose up --build (all services running).

Usage:
    python scripts/demo.py
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import httpx

ORCHESTRATOR = "http://localhost:8085"
SERVICES = {
    "Agent 3 - Log Analyst":      "http://localhost:8081",
    "Agent 1 - Pipeline Monitor": "http://localhost:8082",
    "Gerrit MCP":                  "http://localhost:8083",
    "Agent 4 - Error Analyst":    "http://localhost:8084",
    "Orchestrator":                "http://localhost:8085",
    "Agent 5 - Code Repairer":    "http://localhost:8086",
    "Agent 6 - Review & Notify":  "http://localhost:8087",
}

FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "sample_jenkins_logs"


async def health_check() -> bool:
    """Check all 7 services are running."""
    print("\n=== HEALTH CHECK ===")
    all_ok = True
    async with httpx.AsyncClient(timeout=5) as client:
        for name, base_url in SERVICES.items():
            try:
                resp = await client.get(f"{base_url}/health")
                status = "✅ OK" if resp.status_code == 200 else f"❌ {resp.status_code}"
                if resp.status_code != 200:
                    all_ok = False
            except Exception as exc:
                status = f"❌ {exc}"
                all_ok = False
            print(f"  {name}: {status}")
    return all_ok


async def scenario_a_demo() -> None:
    """Scenario A: ImportError bug → Agent 1→2→3→4→5→6 full pipeline."""
    print("\n=== SCENARIO A: Bug Fix (ImportError) ===")
    log_file = FIXTURE_DIR / "build_failure_import_error.log"
    raw_log = log_file.read_text() if log_file.exists() else "ImportError: cannot import name 'Foo'"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{ORCHESTRATOR}/tools/handle_build_failure",
            json={
                "build_id": "demo-A-001",
                "repo": "example/my-python-app",
                "branch": "main",
                "scenario": "A",
                "raw_log": raw_log,
            },
        )

    result = resp.json()
    status = result.get("status", "UNKNOWN")
    score = result.get("final_score", "N/A")
    print(f"  Result:  {status}")
    print(f"  Score:   {score}")
    print(f"  Reason:  {result.get('reason', '')}")


async def scenario_b_demo() -> None:
    """Scenario B: Feature request → Agent 2→5→6 (no log analysis needed)."""
    print("\n=== SCENARIO B: Feature Development ===")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{ORCHESTRATOR}/tools/handle_build_failure",
            json={
                "build_id": "demo-B-001",
                "repo": "example/my-python-app",
                "branch": "feature/status-endpoint",
                "scenario": "B",
                "task_description": "Add a GET /status endpoint that returns JSON with service name and uptime",
            },
        )

    result = resp.json()
    print(f"  Result:  {result.get('status', 'UNKNOWN')}")
    print(f"  Reason:  {result.get('reason', '')}")


async def yellow_demo() -> None:
    """YELLOW: Mixed text → Agent 2 → human must classify manually."""
    print("\n=== YELLOW: Manual Classification ===")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{ORCHESTRATOR}/tools/handle_build_failure",
            json={
                "build_id": "demo-Y-001",
                "scenario": "YELLOW",
                "task_description": "Fix the authentication bug and also add the new OAuth feature",
            },
        )

    result = resp.json()
    print(f"  Result:  {result.get('status', 'UNKNOWN')}")
    print(f"  Action:  {result.get('action', result.get('reason', ''))}")
    print("  → Human must classify this task manually")


async def show_metrics() -> None:
    """Fetch and display key Prometheus metrics."""
    print("\n=== METRICS (token usage) ===")
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get("http://localhost:8085/metrics")
            lines = [
                line for line in resp.text.split("\n")
                if "agent_tokens_used" in line and not line.startswith("#")
            ]
            if lines:
                for line in lines:
                    print(f"  {line}")
            else:
                print("  (No token usage recorded yet)")
        except Exception as exc:
            print(f"  Could not fetch metrics: {exc}")


async def main() -> None:
    """Run the full demo."""
    print("=" * 60)
    print("  Auto-Healing AI DevOps Platform — Demo")
    print("=" * 60)

    ok = await health_check()
    if not ok:
        print("\n⚠️  Some services are not running.")
        print("   Run: docker-compose up --build")
        print("   Then retry: python scripts/demo.py")
        sys.exit(1)

    await scenario_a_demo()
    await scenario_b_demo()
    await yellow_demo()
    await show_metrics()

    print("\n" + "=" * 60)
    print("  DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
