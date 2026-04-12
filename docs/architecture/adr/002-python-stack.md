# ADR-002: Python 3.11+ with aiohttp/httpx Stack

**Status:** Accepted  
**Date:** 2024-01-15

## Context
All 6 agents and the orchestrator need a common runtime. Agents are I/O-bound (LLM calls,
HTTP requests, file reads). We need async support, good library ecosystem, and fast iteration.

## Decision
Use Python 3.11+ with:
- aiohttp  -- async HTTP server for MCP services
- httpx    -- async HTTP client (inter-agent calls)
- pydantic v2 -- input validation and serialization
- structlog   -- structured JSON logging
- prometheus-client -- metrics export

## Consequences
**Positive:**
- Single language across all agents (no polyglot complexity)
- asyncio handles high concurrency for LLM API calls
- pydantic v2 is 5-10x faster than v1 for validation
- Entire team already knows Python

**Negative:**
- Python GIL limits true CPU parallelism (not relevant for I/O-bound agents)
- Type hints are optional (enforced via mypy in CI)
