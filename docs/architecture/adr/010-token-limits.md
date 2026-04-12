# ADR-010: Per-Agent Token Budget with Hourly Reset

**Status:** Accepted  
**Date:** 2024-01-18

## Context
LLM API costs can spike unexpectedly if agents loop, retry excessively, or receive
abnormally large inputs. We need a safety mechanism that limits per-agent spend per hour.

## Decision
TokenTracker (singleton in src/shared/token_tracker.py) enforces per-agent hourly budgets:

| Agent | Tokens/hour |
|-------|-------------|
| Agent 1 - Pipeline Monitor  |  5,000 |
| Agent 2 - Task Inspector    | 10,000 |
| Agent 3 - Log Analyst       | 15,000 |
| Agent 4 - Error Analyst     | 25,000 |
| Agent 5 - Code Repairer     | 60,000 |
| Agent 6 - Review & Notify   | 10,000 |
| Orchestrator                | 10,000 |
| TOTAL                       |135,000 |

Behavior:
- At 80% usage: log WARNING, continue
- At 100% usage: raise TokenBudgetExceeded -> RED pipeline
- Hourly reset: automatic via _reset_if_new_hour()

Metrics: agent_tokens_used, agent_token_budget_remaining (Prometheus gauges).

## Consequences
**Positive:**
- Hard cap on per-agent hourly API cost
- Warning at 80% gives early visibility before hard stop
- Prometheus metrics enable cost dashboards

**Negative:**
- Hourly reset is wall-clock based (not rolling window)
- Budget limits may need tuning based on real usage patterns
- TokenBudgetExceeded causes pipeline abort (no graceful degradation)
