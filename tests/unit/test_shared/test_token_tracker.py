from __future__ import annotations

import time

import pytest

from src.shared.token_tracker import TokenTracker


@pytest.fixture(autouse=True)
def patch_agent_configs(monkeypatch):
    """Inject small, predictable token limits — no .env required."""
    import src.shared.token_tracker as tt_mod
    from src.shared.config import AgentModelConfig

    fake_configs = {
        "test_agent": AgentModelConfig(
            primary="some-model",
            max_tokens_per_request=100,
            max_tokens_per_hour=1_000,
        ),
        "small_agent": AgentModelConfig(
            primary="some-model",
            max_tokens_per_request=10,
            max_tokens_per_hour=100,
        ),
    }
    monkeypatch.setattr(tt_mod, "AGENT_CONFIGS", fake_configs)


@pytest.fixture
def tracker() -> TokenTracker:
    return TokenTracker()


class TestCheckBudget:
    def test_returns_true_when_within_budget(self, tracker):
        assert tracker.check_budget("test_agent", 500) is True

    def test_returns_false_when_exceeds_budget(self, tracker):
        assert tracker.check_budget("test_agent", 1_001) is False

    def test_returns_false_after_usage_fills_budget(self, tracker):
        tracker.record_usage("test_agent", 900)
        assert tracker.check_budget("test_agent", 200) is False

    def test_exact_limit_is_allowed(self, tracker):
        assert tracker.check_budget("test_agent", 1_000) is True

    def test_one_over_limit_is_blocked(self, tracker):
        assert tracker.check_budget("test_agent", 1_001) is False

    def test_warning_logged_at_80_percent(self, tracker, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            tracker.check_budget("test_agent", 800)
        assert any("token_budget_warning" in r.message for r in caplog.records)

    def test_no_warning_below_80_percent(self, tracker, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            tracker.check_budget("test_agent", 500)
        warning_records = [r for r in caplog.records if "token_budget_warning" in r.message]
        assert warning_records == []


class TestRecordUsage:
    def test_usage_accumulated(self, tracker):
        tracker.record_usage("test_agent", 300)
        tracker.record_usage("test_agent", 200)
        assert tracker.get_used("test_agent") == 500

    def test_remaining_decreases_after_usage(self, tracker):
        tracker.record_usage("test_agent", 400)
        assert tracker.get_remaining("test_agent") == 600

    def test_full_budget_consumed(self, tracker):
        tracker.record_usage("test_agent", 1_000)
        assert tracker.get_remaining("test_agent") == 0
        assert tracker.check_budget("test_agent", 1) is False


class TestHourlyReset:
    def test_reset_after_3600_seconds(self, tracker, monkeypatch):
        tracker.record_usage("test_agent", 900)
        assert tracker.get_used("test_agent") == 900

        # Simulate time advancing past 1 hour
        original_time = time.time
        monkeypatch.setattr(time, "time", lambda: original_time() + 3601)

        assert tracker.get_used("test_agent") == 0
        assert tracker.get_remaining("test_agent") == 1_000

    def test_no_reset_before_3600_seconds(self, tracker, monkeypatch):
        tracker.record_usage("test_agent", 500)

        original_time = time.time
        monkeypatch.setattr(time, "time", lambda: original_time() + 3599)

        assert tracker.get_used("test_agent") == 500


class TestIsolationBetweenAgents:
    def test_agents_tracked_independently(self, tracker):
        tracker.record_usage("test_agent", 800)
        tracker.record_usage("small_agent", 50)
        assert tracker.get_used("test_agent") == 800
        assert tracker.get_used("small_agent") == 50

    def test_one_agent_exhausted_does_not_affect_other(self, tracker):
        tracker.record_usage("small_agent", 100)
        assert tracker.check_budget("small_agent", 1) is False
        assert tracker.check_budget("test_agent", 100) is True
