"""Unit tests for the circuit breaker."""
from __future__ import annotations

import time

import pytest

from src.shared.resilience import CircuitBreaker, CircuitState


class TestCircuitBreakerBasic:
    """Test basic circuit breaker functionality."""

    def test_starts_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_allowed() is True

    def test_success_keeps_closed(self):
        """Recording success should keep circuit CLOSED."""
        cb = CircuitBreaker("test")
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_one_failure_stays_closed(self):
        """A single failure should not trip the breaker."""
        cb = CircuitBreaker("test", failure_threshold=5)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_allowed() is True

    def test_threshold_failures_trip_breaker(self):
        """Recording threshold failures should trip to OPEN."""
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # Not yet
        cb.record_failure()
        assert cb.state == CircuitState.OPEN  # Now it's tripped
        assert cb.is_allowed() is False

    def test_is_allowed_returns_false_when_open(self):
        """is_allowed() should return False when OPEN."""
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_allowed() is False

    def test_success_after_failures_resets(self):
        """Recording success should clear failures and go back to CLOSED."""
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRecovery:
    """Test circuit breaker recovery (HALF_OPEN state)."""

    def test_recovery_timeout_transitions_to_half_open(self):
        """After recovery_timeout, OPEN should transition to HALF_OPEN."""
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_allowed() is True

    def test_half_open_allows_one_probe(self):
        """HALF_OPEN state should allow requests (probe)."""
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        # is_allowed should return True even in HALF_OPEN
        assert cb.is_allowed() is True

    def test_success_from_half_open_closes_circuit(self):
        """Success in HALF_OPEN should close the circuit."""
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerWindow:
    """Test the rolling window for failure counting."""

    def test_old_failures_expire(self):
        """Failures outside the window should not count."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=3,
            window_seconds=0.2,
        )
        cb.record_failure()
        # Failure at t=0
        time.sleep(0.25)  # Wait for window to expire
        # Now record 2 more failures
        cb.record_failure()
        cb.record_failure()
        # Should only have 2 recent failures, not 3
        assert cb.state == CircuitState.CLOSED
        # Add one more to reach threshold
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_window_boundaries(self):
        """Test failures at window boundaries."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=2,
            window_seconds=0.3,
        )
        cb.record_failure()
        time.sleep(0.35)  # Just past the window
        # First failure is now expired
        cb.record_failure()
        # Should only be 1 failure in the window
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerStateTransitions:
    """Test all possible state transitions."""

    def test_closed_to_open(self):
        """CLOSED → OPEN on threshold."""
        cb = CircuitBreaker("test", failure_threshold=2)
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_closed_to_closed_on_success(self):
        """CLOSED → CLOSED on success (no-op)."""
        cb = CircuitBreaker("test")
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_open_to_half_open_on_timeout(self):
        """OPEN → HALF_OPEN on timeout."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        """HALF_OPEN → CLOSED on success."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        """HALF_OPEN → OPEN on failure."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        # After 1 failure in HALF_OPEN (with threshold=1), goes back to OPEN
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerCustomization:
    """Test custom parameters."""

    def test_custom_failure_threshold(self):
        """Custom failure threshold should be respected."""
        cb = CircuitBreaker("test", failure_threshold=10)
        for _ in range(9):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_custom_recovery_timeout(self):
        """Custom recovery timeout should be respected."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.5)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.2)
        assert cb.state == CircuitState.OPEN  # Not yet
        time.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN  # Now

    def test_custom_window_seconds(self):
        """Custom window size should be respected."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=2,
            window_seconds=1.0,
        )
        cb.record_failure()
        time.sleep(0.5)  # Within window
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
