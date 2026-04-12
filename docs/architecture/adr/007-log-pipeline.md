# ADR-007: Log Cleaning Pipeline (Agent 3)

**Status:** Accepted  
**Date:** 2024-01-17

## Context
Raw Jenkins logs contain ANSI escape codes, timestamps, noise lines (gradle progress bars,
download percentages), and duplicates. Sending 50k-character logs to an LLM wastes tokens
and reduces analysis quality.

## Decision
Agent 3 (Log Analyst, port 8081) implements a 5-stage cleaning pipeline:
1. remove_ansi()           -- strip ANSI escape sequences
2. strip_timestamps()      -- remove ISO8601/epoch timestamps
3. filter_noise()          -- drop download%, progress bars, blank lines
4. extract_relevant_lines()-- keep ERROR/WARN/Exception/Traceback lines + context window
5. deduplicate()           -- remove consecutive duplicate lines

Target: reduce log size by >= 70% before LLM analysis.
Metric: log_reduction_ratio (Prometheus gauge).

## Consequences
**Positive:**
- Significant token savings on Agent 4 LLM calls
- Cleaner input improves LLM analysis accuracy
- Each filter is pure function -- easy to test in isolation

**Negative:**
- Aggressive filtering may discard relevant context (tunable via filter config)
- Pipeline adds ~50ms latency per log file
