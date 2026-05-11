"""Generic NVIDIA NIM LLM client — reused by all agents."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from openai import APIError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletion

from src.shared.config import AGENT_CONFIGS
from src.shared.model_fallback import ModelFallbackManager
from src.shared.token_tracker import token_tracker

logger = logging.getLogger(__name__)

_NIM_BASE_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Slot name → (temperature, top_p, max_tokens)
SlotParams = dict[str, tuple[float, float, int]]

_DEFAULT_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (0.2, 0.7, 1024),
    "FALLBACK_1": (0.2, 0.7, 1024),
    "FALLBACK_2": (0.2, 0.7, 1024),
    "FALLBACK_3": (0.2, 0.7, 1024),
}


@dataclass
class _SlotConfig:
    model: str
    api_key: str
    temperature: float
    top_p: float
    max_tokens: int


def load_slot_configs(agent_env_prefix: str,
                      slot_params: SlotParams | None = None) -> dict[str, _SlotConfig]:
    """Load per-model API keys and inference params from environment.

    Args:
        agent_env_prefix: Env var prefix, e.g. "PIPELINE_MONITOR".
        slot_params: Override temperature/top_p/max_tokens per slot.

    Returns:
        Dict mapping model name → SlotConfig. Empty for unconfigured slots.
    """
    params = slot_params or _DEFAULT_SLOT_PARAMS
    slots = [
        ("PRIMARY",    f"{agent_env_prefix}_PRIMARY_MODEL",    f"{agent_env_prefix}_PRIMARY_API_KEY"),
        ("FALLBACK_1", f"{agent_env_prefix}_FALLBACK_1",       f"{agent_env_prefix}_FALLBACK_1_API_KEY"),
        ("FALLBACK_2", f"{agent_env_prefix}_FALLBACK_2",       f"{agent_env_prefix}_FALLBACK_2_API_KEY"),
        ("FALLBACK_3", f"{agent_env_prefix}_FALLBACK_3",       f"{agent_env_prefix}_FALLBACK_3_API_KEY"),
    ]
    configs: dict[str, _SlotConfig] = {}
    for slot_name, model_var, key_var in slots:
        model = os.getenv(model_var, "")
        api_key = os.getenv(key_var, "")
        if model and api_key:
            temp, top_p, max_tok = params.get(slot_name, _DEFAULT_SLOT_PARAMS["PRIMARY"])
            configs[model] = _SlotConfig(
                model=model,
                api_key=api_key,
                temperature=temp,
                top_p=top_p,
                max_tokens=max_tok,
            )
    return configs


class NimClient:
    """NVIDIA NIM chat completion client with fallback chain and token tracking.

    Args:
        agent_name: Key in AGENT_CONFIGS (e.g. "pipeline_monitor").
        agent_env_prefix: Env var prefix (e.g. "PIPELINE_MONITOR").
        slot_params: Per-slot inference parameters. Uses defaults if None.
    """

    def __init__(self, agent_name: str, agent_env_prefix: str,
                 slot_params: SlotParams | None = None) -> None:
        self.agent_name = agent_name
        self._fallback_mgr = ModelFallbackManager(agent_name)
        self._slots = load_slot_configs(agent_env_prefix, slot_params)
        self.last_model: str = ""
        # One OpenAI client per slot — reused across calls to avoid reconnection overhead
        self._clients = {
            model: OpenAI(base_url=_NIM_BASE_URL, api_key=slot.api_key)
            for model, slot in self._slots.items()
        }

    def complete(self, messages: list[dict], max_tokens: int | None = None) -> str:
        """Run a chat completion with automatic model fallback.

        Args:
            messages: OpenAI-format message list.
            max_tokens: Override per-request token limit.

        Returns:
            Model response content string.

        Raises:
            RuntimeError: If token budget exceeded.
            AllModelsFailed: If all fallback models fail.
        """
        config = AGENT_CONFIGS[self.agent_name]
        tokens_needed = max_tokens or config.max_tokens_per_request

        if not token_tracker.check_budget(self.agent_name, tokens_needed):
            raise RuntimeError(
                f"Token budget exceeded for agent '{self.agent_name}'"
            )

        while True:
            model = self._fallback_mgr.get_current_model()
            slot = self._slots.get(model)
            if slot is None:
                self._fallback_mgr.switch_to_next(f"no API key for {model}")
                continue

            client = self._clients[model]
            try:
                response: ChatCompletion = client.chat.completions.create(  # type: ignore[assignment]
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=slot.temperature,
                    top_p=slot.top_p,
                    max_tokens=min(tokens_needed, slot.max_tokens),
                    stream=False,
                )
                content = response.choices[0].message.content or ""
                used = response.usage.total_tokens if response.usage else tokens_needed
                token_tracker.record_usage(self.agent_name, used)
                self._fallback_mgr.reset()
                self.last_model = model
                logger.info("nim_complete agent=%s model=%s tokens=%d",
                            self.agent_name, model, used)
                return content

            except (APIError, APITimeoutError) as exc:
                logger.warning("nim_failed agent=%s model=%s error=%s",
                               self.agent_name, model, exc)
                self._fallback_mgr.switch_to_next(str(exc))
