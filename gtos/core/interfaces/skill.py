"""Skill model and storage protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SkillRecord:
    task: str
    code: str
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillStoreProtocol(ABC):
    @abstractmethod
    def add(self, task: str, code: str, success: bool = True, metadata: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_recent(self, n: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search_by_task(self, query: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[dict[str, Any]]:
        raise NotImplementedError
