"""Resilience utilities — circuit breaker, retry, global fallback."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from src.shared.config import SERVICE_URLS
from src.shared.metrics import agent_fallback_triggered

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Global fallback
# ---------------------------------------------------------------------------

def handle_agent_failure(failed_agent: str,
                          build_id: str,
                          reason: str) -> dict[str, Any]:
    """Trigger the global fallback rule.

    Called when any agent crashes or returns invalid state.
    Returns a RED payload dict for Agent 6's evaluate_and_notify endpoint.
    Raw dict is intentional — avoids circular import with models.py.

    Args:
        failed_agent: Name of the agent that failed.
        build_id: The build ID being processed.
        reason: Error message / reason for failure.
    """
    logger.error(
        "global_fallback_triggered failed_agent=%s build_id=%s reason=%s",
        failed_agent, build_id, reason,
    )
    # Record fallback metric
    agent_fallback_triggered.labels(agent=failed_agent).inc()

    return {
        "build_id": build_id,
        "status": "RED",
        "reason": "agent_failure",
        "failed_agent": failed_agent,
        "message": f"Agent {failed_agent} failed: {reason}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.0,
        "blast_radius": "HIGH",
        "error_type": "UNKNOWN",
    }


async def trigger_global_fallback(failed_agent: str,
                                   build_id: str,
                                   reason: str) -> None:
    """Call Agent 6 directly with RED when an agent crashes.

    Args:
        failed_agent: Name of the failed agent.
        build_id: Build being processed.
        reason: Why the fallback was triggered.
    """
    payload = handle_agent_failure(failed_agent, build_id, reason)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify",
                json=payload,
            )
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.error("global_fallback_notification_failed error=%s", exc)


def validate_agent_output(agent_name: str,
                           output: dict[str, Any],
                           required_fields: list[str]) -> bool:
    """Validate that an agent's output contains all required fields.

    Args:
        agent_name: Name of the agent (for logging).
        output: The dict returned by the agent.
        required_fields: List of field names that must be present.

    Returns:
        True if all fields present, False otherwise.
    """
    missing = [f for f in required_fields if f not in output]
    if missing:
        logger.error(
            "invalid_agent_output agent=%s missing=%s",
            agent_name, missing,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    """States of the circuit breaker."""

    CLOSED = "closed"        # Normal — requests allowed
    OPEN = "open"            # Tripped — requests blocked
    HALF_OPEN = "half_open"  # Cooldown elapsed — allow one probe request


class CircuitBreaker:
    """Circuit breaker for external API calls.

    failure_threshold failures within window_seconds → OPEN.
    recovery_timeout seconds cooldown → HALF_OPEN (one probe allowed).
    On success → CLOSED again.

    Args:
        name: Identifier for this breaker (for logging).
        failure_threshold: Number of failures within window to trip.
        recovery_timeout: Seconds to wait before entering HALF_OPEN.
        window_seconds: Rolling window for counting failures.
    """

    def __init__(self, name: str,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 30.0,
                 window_seconds: float = 60.0) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_seconds = window_seconds
        self._state = CircuitState.CLOSED
        # deque evicts oldest entries automatically — O(1) append/pop
        self._failures: deque[float] = deque()
        self._opened_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        """Return current state.

        Note: reading this property may transition OPEN → HALF_OPEN
        if the recovery timeout has elapsed.
        """
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def is_allowed(self) -> bool:
        """Return True if a request is allowed through."""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful call — resets to CLOSED."""
        self._failures.clear()
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — may trip to OPEN."""
        now = time.time()
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = now
            logger.warning("circuit_breaker_tripped name=%s", self.name)


# Singletons per external service
circuit_breakers: dict[str, CircuitBreaker] = {
    "llm_api":       CircuitBreaker("llm_api"),
    "github_api":    CircuitBreaker("github_api"),
    "jenkins_api":   CircuitBreaker("jenkins_api"),
    "teams_webhook": CircuitBreaker("teams_webhook"),
    "slack_webhook": CircuitBreaker("slack_webhook"),
}


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def with_retry(coro_fn: Callable[[], Awaitable[T]],
                     max_retries: int = 3,
                     delays: list[float] | None = None) -> T:
    """Run a coroutine with exponential backoff retry.

    Args:
        coro_fn: Zero-argument async callable to retry.
        max_retries: Maximum number of retries (default 3).
        delays: Seconds between attempts (default [1, 2, 4]).
                Last value is reused if attempts exceed list length.

    Returns:
        Result of coro_fn on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    if delays is None:
        delays = [1.0, 2.0, 4.0]

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            last_error = exc
            if attempt < max_retries:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    "retry attempt=%d/%d delay=%.1fs error=%s",
                    attempt + 1, max_retries, delay, exc,
                )
                await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
