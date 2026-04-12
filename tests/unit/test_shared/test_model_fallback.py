from __future__ import annotations

import pytest

from src.shared.model_fallback import AllModelsFailed, ModelFallbackManager


@pytest.fixture(autouse=True)
def patch_agent_configs(monkeypatch):
    """Inject deterministic model configs — no .env required."""
    import src.shared.model_fallback as mf_mod
    from src.shared.config import AgentModelConfig

    fake_configs = {
        "code_repairer": AgentModelConfig(
            primary="model-primary",
            fallback_1="model-fb1",
            fallback_2="model-fb2",
            fallback_3="model-fb3",
            max_tokens_per_request=4000,
            max_tokens_per_hour=50_000,
        ),
        "empty_agent": AgentModelConfig(),  # all slots empty
        "single_model_agent": AgentModelConfig(primary="only-model"),
    }
    monkeypatch.setattr(mf_mod, "AGENT_CONFIGS", fake_configs)


class TestModelFallbackManagerInit:
    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            ModelFallbackManager("nonexistent_agent")

    def test_valid_agent_initialises(self):
        mgr = ModelFallbackManager("code_repairer")
        assert mgr.agent_name == "code_repairer"


class TestGetCurrentModel:
    def test_returns_primary_initially(self):
        mgr = ModelFallbackManager("code_repairer")
        assert mgr.get_current_model() == "model-primary"

    def test_empty_config_raises_value_error(self):
        mgr = ModelFallbackManager("empty_agent")
        with pytest.raises(ValueError, match="No models configured"):
            mgr.get_current_model()


class TestSwitchToNext:
    def test_switches_to_fallback_1(self):
        mgr = ModelFallbackManager("code_repairer")
        next_model = mgr.switch_to_next("timeout")
        assert next_model == "model-fb1"

    def test_switches_through_all_fallbacks(self):
        mgr = ModelFallbackManager("code_repairer")
        assert mgr.switch_to_next("err") == "model-fb1"
        assert mgr.switch_to_next("err") == "model-fb2"
        assert mgr.switch_to_next("err") == "model-fb3"

    def test_all_models_exhausted_raises(self):
        mgr = ModelFallbackManager("code_repairer")
        mgr.switch_to_next("e1")
        mgr.switch_to_next("e2")
        mgr.switch_to_next("e3")
        with pytest.raises(AllModelsFailed):
            mgr.switch_to_next("e4")

    def test_single_model_raises_on_first_switch(self):
        mgr = ModelFallbackManager("single_model_agent")
        assert mgr.get_current_model() == "only-model"
        with pytest.raises(AllModelsFailed):
            mgr.switch_to_next("timeout")


class TestReset:
    def test_reset_returns_to_primary(self):
        mgr = ModelFallbackManager("code_repairer")
        mgr.switch_to_next("timeout")
        mgr.switch_to_next("timeout")
        mgr.reset()
        assert mgr.get_current_model() == "model-primary"

    def test_reset_from_exhausted_state(self):
        mgr = ModelFallbackManager("code_repairer")
        for _ in range(3):
            mgr.switch_to_next("err")
        with pytest.raises(AllModelsFailed):
            mgr.switch_to_next("err")
        mgr.reset()
        assert mgr.get_current_model() == "model-primary"
