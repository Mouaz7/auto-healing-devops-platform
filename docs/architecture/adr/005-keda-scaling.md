# ADR-005: KEDA-Based Auto-Scaling (Future)

**Status:** Proposed  
**Date:** 2024-01-16

## Context
Under high load, multiple Jenkins builds may trigger simultaneously. Each agent service
needs to scale independently based on queue depth or CPU usage.

## Decision
Plan for KEDA (Kubernetes Event Driven Autoscaling) in production:
- ScaledObject per agent service
- Scale trigger: HTTP request queue depth > 5
- Min replicas: 1, Max replicas: 10 per agent
- Scale-to-zero disabled (keep 1 always warm)

For development/exam: single replica per service via docker-compose.

## Consequences
**Positive:**
- Agents scale independently (Agent 5 LLM calls are slow -- needs more replicas)
- KEDA handles scale-down automatically (cost savings)
- No code changes needed -- pure infra config

**Negative:**
- Requires Kubernetes (not needed for exam/dev environment)
- Stateful agents (circuit breakers) need sticky sessions or shared Redis state
- KEDA adds cluster-level complexity
