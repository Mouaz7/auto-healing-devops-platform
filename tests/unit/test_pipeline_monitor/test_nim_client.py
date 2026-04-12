from __future__ import annotations

import pytest

from src.jenkins_mcp.nim_client import NimClient, _load_slot_configs


@pytest.fixture(autouse=True)
def patch_agent_configs(monkeypatch):
    """Inject test agent config and NIM slot configs."""
    import src.shared.model_fallback as mf_mod
    import src.shared.token_tracker as tt_mod
    from src.shared.config import AgentModelConfig

    fake_configs = {
        "pipeline_monitor": AgentModelConfig(
            primary="model-a",
            fallback_1="model-b",
            max_tokens_per_request=100,
            max_tokens_per_hour=10_000,
        ),
        "no_models_agent": AgentModelConfig(),
    }
    monkeypatch.setattr(mf_mod, "AGENT_CONFIGS", fake_configs)
    monkeypatch.setattr(tt_mod, "AGENT_CONFIGS", fake_configs)


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_MONITOR_PRIMARY_MODEL",    "model-a")
    monkeypatch.setenv("PIPELINE_MONITOR_PRIMARY_API_KEY",  "key-a")
    monkeypatch.setenv("PIPELINE_MONITOR_FALLBACK_1",       "model-b")
    monkeypatch.setenv("PIPELINE_MONITOR_FALLBACK_1_API_KEY", "key-b")


class TestLoadSlotConfigs:
    def test_loads_configured_slots(self, monkeypatch):
        configs = _load_slot_configs("PIPELINE_MONITOR")
        assert "model-a" in configs
        assert configs["model-a"].api_key == "key-a"

    def test_skips_empty_slots(self, monkeypatch):
        configs = _load_slot_configs("PIPELINE_MONITOR")
        assert "model-c" not in configs

    def test_temperature_per_slot(self, monkeypatch):
        configs = _load_slot_configs("PIPELINE_MONITOR")
        assert configs["model-a"].temperature == 0.2
        assert configs["model-b"].temperature == 0.1  # FALLBACK_1 is 0.1


class TestNimClientComplete:
    def test_calls_openai_client(self, monkeypatch):
        responses = []

        class FakeUsage:
            total_tokens = 10

        class FakeMessage:
            content = "PROCESS"

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]
            usage = FakeUsage()

        class FakeCompletions:
            def create(self, **kwargs):
                responses.append(kwargs["model"])
                return FakeResponse()

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            chat = FakeChat()
            def __init__(self, **kwargs):
                pass

        monkeypatch.setattr("src.shared.nim_client.OpenAI", FakeOpenAI)
        client = NimClient("pipeline_monitor", "PIPELINE_MONITOR")
        result = client.complete([{"role": "user", "content": "test"}])

        assert result == "PROCESS"
        assert "model-a" in responses

    def test_fallback_on_api_error(self, monkeypatch):
        call_count = [0]

        class FakeUsage:
            total_tokens = 10

        class FakeMessage:
            content = "PROCESS"

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]
            usage = FakeUsage()

        class FakeCompletions:
            def create(self, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    from openai import APITimeoutError
                    raise APITimeoutError(request=None)
                return FakeResponse()

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            chat = FakeChat()
            def __init__(self, **kwargs):
                pass

        monkeypatch.setattr("src.shared.nim_client.OpenAI", FakeOpenAI)
        client = NimClient("pipeline_monitor", "PIPELINE_MONITOR")
        result = client.complete([{"role": "user", "content": "test"}])

        assert result == "PROCESS"
        assert call_count[0] == 2  # primary failed, fallback succeeded

    def test_budget_exceeded_raises(self, monkeypatch):
        import src.shared.token_tracker as tt_mod
        from src.shared.config import AgentModelConfig

        # Set a tiny budget, then exhaust it
        tiny_configs = {
            "pipeline_monitor": AgentModelConfig(
                primary="model-a",
                max_tokens_per_request=100,
                max_tokens_per_hour=50,
            )
        }
        monkeypatch.setattr(tt_mod, "AGENT_CONFIGS", tiny_configs)
        tracker = tt_mod.TokenTracker()
        monkeypatch.setattr(tt_mod, "token_tracker", tracker)
        import src.shared.nim_client as nim_mod
        monkeypatch.setattr(nim_mod, "token_tracker", tracker)

        tracker.record_usage("pipeline_monitor", 50)

        client = NimClient("pipeline_monitor", "PIPELINE_MONITOR")
        with pytest.raises(RuntimeError, match="Token budget exceeded"):
            client.complete([{"role": "user", "content": "x"}])
