"""Agent 1 NIM client — thin wrapper around the shared NimClient.

Per-slot inference params for Agent 1 (fast binary classification):
  PRIMARY    0.2 / 0.7 / 1024
  FALLBACK_1 0.1 / 0.7 / 512   (slightly lower temp for determinism)
  FALLBACK_2 0.2 / 0.7 / 1024
  FALLBACK_3 0.2 / 0.7 / 1024
"""
from __future__ import annotations

from src.shared.nim_client import NimClient, SlotParams, load_slot_configs

__all__ = ["NimClient", "SlotParams", "load_slot_configs"]

_SLOT_PARAMS: SlotParams = {
    "PRIMARY":    (0.2, 0.7, 1024),
    "FALLBACK_1": (0.1, 0.7, 512),
    "FALLBACK_2": (0.2, 0.7, 1024),
    "FALLBACK_3": (0.2, 0.7, 1024),
}


def _load_slot_configs(agent_prefix: str) -> dict:  # type: ignore[type-arg]
    """Return model → SlotConfig for all configured slots (Agent 1 params)."""
    return load_slot_configs(agent_prefix, _SLOT_PARAMS)
