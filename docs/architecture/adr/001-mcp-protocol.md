# ADR-001: MCP (Model Context Protocol) as Service Interface

**Status:** Accepted  
**Date:** 2024-01-15

## Context
The platform needs a standardized way for agents to expose tools, health checks, and metrics.
Each agent runs as an independent microservice. We need a protocol that supports tool discovery,
structured input/output, and HTTP-based communication.

## Decision
Use the Model Context Protocol (MCP) as the standard interface for all agent services.
Every agent exposes:
- POST /tools/{tool_name} -- MCP tool endpoints
- GET /health             -- readiness probe
- GET /metrics            -- Prometheus metrics

## Consequences
**Positive:**
- Uniform interface across all 6 agents + orchestrator
- Tool discovery built-in to the protocol
- Compatible with Claude API tool use
- Enables easy addition of new agents

**Negative:**
- MCP adds a small serialization overhead vs raw HTTP
- Agents must implement MCPServiceBase (minor boilerplate)
