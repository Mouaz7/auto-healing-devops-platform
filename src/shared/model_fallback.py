"""Model fallback manager — primary → fallback1 → fallback2 → fallback3."""
from __future__ import annotations

import logging

from src.shared.config import AGENT_CONFIGS, AgentModelConfig
from src.shared.metrics import agent_model_switches

logger = logging.getLogger(__name__)


class AllModelsFailed(Exception):
    """Raised when all 4 models in the fallback chain have failed."""


class ModelFallbackManager:
    """Manages model fallback for one agent.

    Usage:
        mgr = ModelFallbackManager("code_repairer")
        model = mgr.get_current_model()
        # on failure:
        model = mgr.switch_to_next("timeout")
        # on success:
        mgr.reset()
    """

    def __init__(self, agent_name: str) -> None:
        if agent_name not in AGENT_CONFIGS:
            raise ValueError(f"Unknown agent: '{agent_name}'")
        self.agent_name = agent_name
        self.config: AgentModelConfig = AGENT_CONFIGS[agent_name]
        self._current_index: int = 0

    def get_current_model(self) -> str:
        """Return the currently active model name.

        Raises:
            ValueError: If no models are configured for this agent.
            AllModelsFailed: If all models have been exhausted.
        """
        chain = self.config.fallback_chain
        if not chain:
            raise ValueError(
                f"No models configured for agent '{self.agent_name}'. "
                f"Set {self.agent_name.upper()}_PRIMARY_MODEL in .env"
            )
        if self._current_index >= len(chain):
            raise AllModelsFailed(
                f"All {len(chain)} models failed for agent '{self.agent_name}'"
            )
        return chain[self._current_index]

    def switch_to_next(self, reason: str) -> str:
        """Switch to the next model in the fallback chain.

        Args:
            reason: Why the current model failed (for logging).

        Returns:
            The new model name.

        Raises:
            AllModelsFailed: If there are no more models to try.
        """
        current = self.get_current_model()
        self._current_index += 1
        try:
            next_model = self.get_current_model()
            logger.warning(
                "model_fallback agent=%s from=%s to=%s reason=%s",
                self.agent_name, current, next_model, reason,
            )
            # Track model switch
            agent_model_switches.labels(agent=self.agent_name, reason=reason).inc()
            return next_model
        except AllModelsFailed:
            logger.error(
                "all_models_failed agent=%s reason=%s",
                self.agent_name, reason,
            )
            raise

    def reset(self) -> None:
        """Reset to the primary model (call after a successful request)."""
        self._current_index = 0
