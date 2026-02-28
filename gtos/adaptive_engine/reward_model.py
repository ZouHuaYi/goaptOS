"""Reward model for adaptive bandit updates."""

from __future__ import annotations

from typing import Any


class RewardModel:
    def __init__(
        self,
        success_weight: float = 1.0,
        retry_penalty: float = 0.1,
        latency_penalty: float = 0.00002,
        token_penalty: float = 0.0001,
    ) -> None:
        self.success_weight = float(success_weight)
        self.retry_penalty = float(retry_penalty)
        self.latency_penalty = float(latency_penalty)
        self.token_penalty = float(token_penalty)

    def calculate(self, result: dict[str, Any]) -> float:
        reward = 0.0
        if bool(result.get("success")):
            reward += self.success_weight
        retries = self._retry_count(result)
        reward -= float(retries) * self.retry_penalty
        latency_ms = float((result.get("_metrics", {}) or {}).get("latency_ms", 0.0) or 0.0)
        reward -= latency_ms * self.latency_penalty
        token_cost = self._estimate_token_cost(result)
        reward -= token_cost * self.token_penalty
        return round(reward, 6)

    def _retry_count(self, result: dict[str, Any]) -> int:
        if result.get("summary"):
            return int((result.get("summary", {}) or {}).get("retried_nodes", 0) or 0)
        attempts = int((result.get("_execution", {}) or {}).get("attempts", 1) or 1)
        return max(0, attempts - 1)

    def _estimate_token_cost(self, result: dict[str, Any]) -> int:
        text = "\n".join(
            [
                str(result.get("task", "") or ""),
                str(result.get("code", "") or ""),
                str(result.get("stdout", "") or ""),
                str(result.get("stderr", "") or ""),
            ]
        )
        return max(1, len(text) // 4)
