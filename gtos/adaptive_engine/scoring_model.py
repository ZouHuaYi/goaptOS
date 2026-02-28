"""Scoring model for adaptive capability prioritization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gtos.adaptive_engine.capability_registry import CapabilityMeta


@dataclass(slots=True)
class ScoreWeights:
    success_rate: float = 0.55
    avg_time_ms: float = 0.15
    avg_retries: float = 0.12
    avg_token_cost: float = 0.08
    risk_level: float = 0.10


class CapabilityScoringModel:
    def __init__(self, base_weights: ScoreWeights | None = None) -> None:
        self._base = base_weights or ScoreWeights()

    def dynamic_weights(self, task_profile: dict[str, Any]) -> ScoreWeights:
        w = ScoreWeights(
            success_rate=self._base.success_rate,
            avg_time_ms=self._base.avg_time_ms,
            avg_retries=self._base.avg_retries,
            avg_token_cost=self._base.avg_token_cost,
            risk_level=self._base.risk_level,
        )
        risk = str(task_profile.get("risk_level", "low"))
        complexity = float(task_profile.get("complexity_score", 0.5) or 0.5)
        if risk in {"high", "blocked"}:
            w.risk_level += 0.12
            w.success_rate += 0.08
        elif risk == "medium":
            w.risk_level += 0.05
        if complexity < 0.35:
            w.avg_time_ms += 0.08
            w.avg_token_cost += 0.04
        if bool(task_profile.get("time_sensitive", False)):
            w.avg_time_ms += 0.12
            w.avg_token_cost += 0.05
        return w

    def score(self, capability: CapabilityMeta, task_profile: dict[str, Any]) -> float:
        w = self.dynamic_weights(task_profile)
        time_penalty = min(1.0, capability.avg_time_ms / 12000.0)
        retry_penalty = min(1.0, capability.avg_retries / 5.0)
        token_penalty = min(1.0, capability.avg_token_cost / 3000.0)
        risk_penalty = min(1.0, capability.risk_level)
        raw = (
            w.success_rate * capability.success_rate
            - w.avg_time_ms * time_penalty
            - w.avg_retries * retry_penalty
            - w.avg_token_cost * token_penalty
            - w.risk_level * risk_penalty
        )
        return round(raw, 6)
