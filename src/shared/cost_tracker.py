"""API cost estimator — token-based pricing per build.

Estimates the USD cost of each NVIDIA NIM API call based on the model name
and token count. Pricing is approximate and based on NIM public pricing tiers.

The cost tracker is useful for:
  - Thesis evaluation: "Average cost per auto-fixed build: $0.0023"
  - Budget alerting: warn when a single build exceeds a threshold
  - `/api/stats` endpoint: cumulative cost this session

Usage:
    from src.shared.cost_tracker import cost_tracker
    cost_tracker.record("code_repairer", model="qwen/qwen2.5-coder-32b-instruct",
                        prompt_tokens=1200, completion_tokens=300)
    print(cost_tracker.get_build_cost("build-001"))
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# USD per 1 000 tokens — approximate NIM pricing tiers (April 2026)
# These are conservative estimates; actual prices vary by model and volume.
_PRICING: list[tuple[tuple[str, ...], float]] = [
    # (model name fragments)          $/1K tokens
    (("1b", "3b", "gemma-3-1b"),      0.00010),   # sub-3B: cheapest tier
    (("7b", "8b", "mini"),             0.00020),   # 7-8B
    (("27b", "32b", "small"),          0.00060),   # 27-32B
    (("70b", "72b", "large"),          0.00180),   # 70-72B
    (("120b", "122b", "super"),        0.00400),   # 100-125B
    (("480b", "671b", "405b"),         0.01200),   # 400B+
]
_DEFAULT_PRICE = 0.00060  # fallback: assume a mid-tier model

# Warn when a single build costs more than this
_COST_WARN_THRESHOLD_USD = 0.10


def _price_per_1k(model_name: str) -> float:
    """Look up the $/1K-token price for *model_name*."""
    name_lower = model_name.lower()
    for fragments, price in _PRICING:
        if any(frag in name_lower for frag in fragments):
            return price
    return _DEFAULT_PRICE


@dataclass
class BuildCostRecord:
    """Accumulated cost and token breakdown for one build_id."""

    build_id: str
    total_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    breakdown: list[dict] = field(default_factory=list)


class CostTracker:
    """Thread-safe per-build cost accumulator.

    Records are kept in memory for the session lifetime. The `/api/stats`
    endpoint exposes cumulative totals and per-build breakdown.
    """

    def __init__(self) -> None:
        self._records: dict[str, BuildCostRecord] = defaultdict(
            lambda: BuildCostRecord(build_id="")
        )
        self._lock = threading.Lock()
        self._session_total_usd: float = 0.0

    def record(
        self,
        build_id: str,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Record one API call and return the cost in USD."""
        price = _price_per_1k(model)
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = (total_tokens / 1000.0) * price

        with self._lock:
            rec = self._records[build_id]
            if not rec.build_id:
                rec.build_id = build_id
            rec.total_usd += cost_usd
            rec.prompt_tokens += prompt_tokens
            rec.completion_tokens += completion_tokens
            rec.calls += 1
            rec.breakdown.append({
                "agent":             agent,
                "model":             model,
                "prompt_tokens":     prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd":          round(cost_usd, 6),
            })
            self._session_total_usd += cost_usd

            if rec.total_usd >= _COST_WARN_THRESHOLD_USD:
                logger.warning(
                    "cost_warn build_id=%s total_usd=%.4f threshold=%.2f",
                    build_id, rec.total_usd, _COST_WARN_THRESHOLD_USD,
                )

        logger.debug(
            "cost_recorded build_id=%s agent=%s model=%s tokens=%d cost_usd=%.6f",
            build_id, agent, model, total_tokens, cost_usd,
        )
        return cost_usd

    def get_build_cost(self, build_id: str) -> BuildCostRecord | None:
        """Return the cost record for *build_id*, or None if not tracked."""
        with self._lock:
            rec = self._records.get(build_id)
            return rec if (rec and rec.build_id) else None

    def session_summary(self) -> dict:
        """Return session-wide totals for /api/stats."""
        with self._lock:
            n_builds = sum(1 for r in self._records.values() if r.build_id)
            total_tokens = sum(
                r.prompt_tokens + r.completion_tokens
                for r in self._records.values() if r.build_id
            )
            return {
                "session_total_usd":    round(self._session_total_usd, 6),
                "builds_tracked":       n_builds,
                "total_tokens_used":    total_tokens,
                "avg_cost_per_build":   round(
                    self._session_total_usd / n_builds if n_builds else 0, 6
                ),
            }

    def all_builds(self) -> list[dict]:
        """Return cost breakdown for every tracked build (sorted by cost desc)."""
        with self._lock:
            records = [
                {
                    "build_id":          r.build_id,
                    "total_usd":         round(r.total_usd, 6),
                    "calls":             r.calls,
                    "prompt_tokens":     r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                }
                for r in self._records.values() if r.build_id
            ]
        return sorted(records, key=lambda x: x["total_usd"], reverse=True)


# Global singleton
cost_tracker = CostTracker()
