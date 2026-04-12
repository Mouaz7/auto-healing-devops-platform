# ADR-003: Event-Driven Pipeline (HTTP Chaining)

**Status:** Accepted  
**Date:** 2024-01-16

## Context
The 6 agents need to communicate in sequence: Agent 1 triggers Agent 3, which triggers Agent 4,
etc. Options considered: message queue (Kafka/RabbitMQ), event bus, or direct HTTP chaining.

## Decision
Use direct async HTTP calls chained by the Orchestrator. Each agent call is awaited before
the next agent is called. The Orchestrator (port 8085) owns the pipeline state machine with
VALID_TRANSITIONS enforcement.

## Consequences
**Positive:**
- Simple to debug (linear call stack, no queue inspection needed)
- No extra infrastructure (no Kafka, no RabbitMQ)
- Each step is synchronous within the pipeline -- easy error propagation
- WorkflowState is updated atomically at each transition

**Negative:**
- No built-in replay if orchestrator crashes mid-pipeline
- All agents must be healthy simultaneously (mitigated by circuit breakers)
- Does not scale to fan-out patterns without refactoring
