# ADR-006: Dedicated Orchestrator MCP Service

**Status:** Accepted  
**Date:** 2024-01-17

## Context
The 6 agents are stateless workers. Something needs to own the pipeline state machine,
route scenarios (A/B/YELLOW), and coordinate the agent chain. Options: embed orchestration
in Agent 1, use a dedicated orchestrator, or use a workflow engine (Airflow, Prefect).

## Decision
Implement a dedicated Orchestrator MCP service (port 8085) that:
- Owns WorkflowState and VALID_TRANSITIONS state machine
- Routes scenarios via ScenarioRouter (A: full chain, B: Agent 5+6, YELLOW: human)
- Calls all agents via httpx (async)
- Triggers global fallback on any agent crash
- Exposes handle_build_failure MCP tool as the single entry point

## Consequences
**Positive:**
- Single source of truth for pipeline state
- Agents remain stateless and independently testable
- ScenarioRouter logic is isolated and easy to unit test
- Global fallback is centralized

**Negative:**
- Orchestrator is a single point of failure (mitigated by Docker health checks + restart policy)
- All inter-agent traffic goes through orchestrator (slight latency overhead)
