"""Shared configuration — agent model config + token limits + service URLs."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class AgentModelConfig:  # pylint: disable=too-many-instance-attributes
    """Model configuration for one agent. Model names are set via .env — never hardcoded."""

    primary: str = ""
    fallback_1: str = ""
    fallback_2: str = ""
    fallback_3: str = ""
    max_tokens_per_request: int = 1000
    max_tokens_per_hour: int = 10000
    max_input_tokens: int = 2000
    timeout_seconds: int = 30

    @property
    def fallback_chain(self) -> list[str]:
        """Return list of configured models, skipping empty slots."""
        return [
            m for m in [self.primary, self.fallback_1, self.fallback_2, self.fallback_3]
            if m
        ]


def _load(prefix: str, max_req: int, max_hour: int,
          max_input: int, timeout: int) -> AgentModelConfig:
    """Load agent model config from environment variables."""
    return AgentModelConfig(
        primary=os.getenv(f"{prefix}_PRIMARY_MODEL", ""),
        fallback_1=os.getenv(f"{prefix}_FALLBACK_1", ""),
        fallback_2=os.getenv(f"{prefix}_FALLBACK_2", ""),
        fallback_3=os.getenv(f"{prefix}_FALLBACK_3", ""),
        max_tokens_per_request=max_req,
        max_tokens_per_hour=max_hour,
        max_input_tokens=max_input,
        timeout_seconds=timeout,
    )


# Token limits per agent — no model names hardcoded
AGENT_CONFIGS: dict[str, AgentModelConfig] = {
    "pipeline_monitor": _load("PIPELINE_MONITOR", 500, 5_000, 1_000, 10),
    "task_inspector":   _load("TASK_INSPECTOR",   1_000, 10_000, 2_000, 15),
    "log_analyst":      _load("LOG_ANALYST",      2_000, 20_000, 8_000, 30),
    "error_analyst":    _load("ERROR_ANALYST",    3_000, 30_000, 6_000, 30),
    "code_repairer":    _load("CODE_REPAIRER",    4_000, 50_000, 8_000, 60),
    "review_notify":    _load("REVIEW_NOTIFY",    2_000, 20_000, 4_000, 20),
}

GLOBAL_MAX_CONCURRENT_PIPELINES: int = 3  # referenced by tests/integration/test_load.py
TOKEN_BUDGET_WARNING_PCT: float = 0.80

# Internal service URLs (set via docker-compose environment)
SERVICE_URLS: dict[str, str] = {
    "log_cleaner":    os.getenv("LOG_CLEANER_URL",    "http://localhost:8081"),
    "jenkins":        os.getenv("JENKINS_URL",        "http://localhost:8082"),
    "gerrit":         os.getenv("GERRIT_URL",         "http://localhost:8083"),
    "knowledge_graph": os.getenv("KNOWLEDGE_GRAPH_URL", "http://localhost:8084"),
    "orchestrator":   os.getenv("ORCHESTRATOR_URL",   "http://localhost:8085"),
    "llm":            os.getenv("LLM_URL",            "http://localhost:8086"),
    "notification":   os.getenv("NOTIFICATION_URL",   "http://localhost:8087"),
}

# Per-call HTTP timeouts (seconds). Tunable via env so ops can adjust without redeploy.
# generate_fix can take up to LLM-mcp's full retry budget (≈9 × 120 s + overhead).
# Set higher than that ceiling so the orchestrator never times out before LLM-mcp
# finishes legitimate retries — the alternative is a premature ReadTimeout that
# triggers global_fallback and a late RED Slack alert.
LLM_FIX_TIMEOUT: float = float(os.getenv("LLM_FIX_TIMEOUT", "1200"))
GERRIT_FETCH_TIMEOUT: float = float(os.getenv("GERRIT_FETCH_TIMEOUT", "10"))
