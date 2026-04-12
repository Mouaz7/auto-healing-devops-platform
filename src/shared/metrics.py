"""Prometheus metrics for all 6 agents."""
from __future__ import annotations

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Pipeline metrics
# ---------------------------------------------------------------------------

workflows_total = Counter(
    "auto_healer_workflows_total",
    "Total number of workflows processed",
    ["status"],  # completed, failed, blocked
)

confidence_score = Histogram(
    "auto_healer_confidence_score",
    "Traffic light confidence score distribution",
    ["traffic_light"],  # GREEN, YELLOW, RED
    buckets=[0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0],
)

fix_duration_seconds = Histogram(
    "auto_healer_fix_duration_seconds",
    "Time from trigger to fix submission",
    buckets=[5, 10, 30, 60, 120, 300],
)

log_reduction_ratio = Gauge(
    "auto_healer_log_reduction_ratio",
    "Agent 3 log reduction percentage (last run)",
)

quality_gate_results = Counter(
    "auto_healer_quality_gate_results",
    "Bandit/Pylint quality gate results",
    ["gate", "result"],  # gate: bandit/pylint, result: pass/fail
)

# ---------------------------------------------------------------------------
# Agent-specific metrics
# ---------------------------------------------------------------------------

agent_model_switches = Counter(
    "agent_model_switch_total",
    "Number of model switches per agent",
    ["agent", "reason"],
)

agent_tokens_used = Gauge(
    "agent_tokens_used",
    "Tokens used this hour per agent",
    ["agent"],
)

agent_token_budget_remaining = Gauge(
    "agent_token_budget_remaining",
    "Remaining token budget this hour per agent",
    ["agent"],
)

agent_fallback_triggered = Counter(
    "agent_fallback_triggered_total",
    "Number of global fallback events per agent",
    ["agent"],
)


def generate_metrics_output() -> str:
    """Return Prometheus text format metrics for /metrics endpoint."""
    return generate_latest().decode("utf-8")
