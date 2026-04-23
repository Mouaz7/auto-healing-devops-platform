"""Token budget tracker — per agent, per hour.

Thread-safe: all mutations are protected by a Lock so concurrent LLM calls
across asyncio tasks (running in a thread pool) cannot race on _usage.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

from src.shared.config import AGENT_CONFIGS, TOKEN_BUDGET_WARNING_PCT
from src.shared.metrics import agent_tokens_used, agent_token_budget_remaining

logger = logging.getLogger(__name__)


class TokenTracker:
    """Tracks token usage per agent per hour.

    Resets automatically every 3600 seconds.
    Warns at 80% of the hourly limit.
    Hard stop at 100%.
    """

    def __init__(self) -> None:
        self._usage: dict[str, int] = defaultdict(int)
        self._window_start: float = time.time()
        self._lock = threading.Lock()

    def _reset_if_new_hour(self) -> None:
        """Must be called with self._lock held."""
        if time.time() - self._window_start >= 3600:
            self._usage.clear()
            self._window_start = time.time()
            logger.info("token_tracker_reset")

    def check_budget(self, agent_name: str, requested_tokens: int) -> bool:
        """Return True if the agent has budget for *requested_tokens*."""
        with self._lock:
            self._reset_if_new_hour()
            config = AGENT_CONFIGS[agent_name]
            current = self._usage[agent_name]
            projected = current + requested_tokens

            if projected > config.max_tokens_per_hour:
                logger.warning(
                    "token_budget_exceeded agent=%s used=%d requested=%d limit=%d",
                    agent_name, current, requested_tokens, config.max_tokens_per_hour,
                )
                return False

            warning_threshold = int(config.max_tokens_per_hour * TOKEN_BUDGET_WARNING_PCT)
            if projected >= warning_threshold:
                pct = round(projected / config.max_tokens_per_hour * 100)
                logger.warning(
                    "token_budget_warning agent=%s used_pct=%d%%",
                    agent_name, pct,
                )
            return True

    def record_usage(self, agent_name: str, tokens_used: int) -> None:
        """Record actual token usage after a successful LLM call."""
        with self._lock:
            self._reset_if_new_hour()
            self._usage[agent_name] += tokens_used

        # Prometheus updates outside the lock (reads are safe without it)
        agent_tokens_used.labels(agent=agent_name).set(self._usage[agent_name])
        remaining = self.get_remaining(agent_name)
        agent_token_budget_remaining.labels(agent=agent_name).set(remaining)

    def get_remaining(self, agent_name: str) -> int:
        """Return remaining tokens for *agent_name* this hour."""
        with self._lock:
            self._reset_if_new_hour()
            config = AGENT_CONFIGS[agent_name]
            return config.max_tokens_per_hour - self._usage[agent_name]

    def get_used(self, agent_name: str) -> int:
        """Return tokens used by *agent_name* this hour."""
        with self._lock:
            self._reset_if_new_hour()
            return self._usage[agent_name]

    def usage_snapshot(self) -> dict[str, int]:
        """Return a copy of the current usage dict (safe for serialisation)."""
        with self._lock:
            self._reset_if_new_hour()
            return dict(self._usage)


# Global singleton — imported by all agents
token_tracker = TokenTracker()
