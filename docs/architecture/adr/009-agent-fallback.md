# ADR-009: Per-Agent Model Fallback Chain

**Status:** Accepted  
**Date:** 2024-01-18

## Context
LLM API calls can fail (rate limits, timeouts, provider outages). The platform must not
halt the pipeline on a single model failure. Each agent needs resilience to model failures.

## Decision
Each agent has a 4-slot model config (primary + 3 fallbacks) loaded from environment variables:
  PRIMARY_MODEL, FALLBACK_1_MODEL, FALLBACK_2_MODEL, FALLBACK_3_MODEL

ModelFallbackManager iterates the chain on each failure.
If all 4 models fail: raise AllModelsFailed -> handle_agent_failure() -> global RED pipeline.

Fallback is tracked via:
- agent_model_switches Prometheus counter (per agent + reason)
- structlog warning on each switch

## Consequences
**Positive:**
- Pipeline survives single model provider outages
- Each agent can use different model providers in its fallback chain
- Fallback switches are visible in metrics and logs

**Negative:**
- Fallback models may have different capabilities/output formats
- AllModelsFailed is a hard stop -- no partial results
- 4 models per agent means 24 model slots to configure (via .env)
