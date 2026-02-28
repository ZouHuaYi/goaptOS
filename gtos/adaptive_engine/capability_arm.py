"""Bandit capability arm model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class CapabilityArm:
    name: str
    total_reward: float = 0.0
    pull_count: int = 0

    @property
    def average_reward(self) -> float:
        if self.pull_count <= 0:
            return 0.0
        return float(self.total_reward) / float(self.pull_count)

    def update(self, reward: float) -> None:
        self.pull_count += 1
        self.total_reward += float(reward)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "CapabilityArm":
        return CapabilityArm(
            name=str(payload.get("name", "")),
            total_reward=float(payload.get("total_reward", 0.0) or 0.0),
            pull_count=int(payload.get("pull_count", 0) or 0),
        )
