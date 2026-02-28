"""Base abstraction for role-oriented agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    def __init__(self, role: str, profile: dict[str, Any] | None = None) -> None:
        self.role = role
        self.profile = profile or {}

    @abstractmethod
    def think(self, task: str, context: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def act(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

