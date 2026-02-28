"""Unified task abstractions used by orchestrator and executors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TaskSpec:
    """Normalized task model shared by single-task and DAG execution."""

    task_id: str
    prompt: str
    deps: list[str] = field(default_factory=list)
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskExecutor(ABC):
    """Unified task executor interface."""

    @abstractmethod
    def execute_task(self, task_prompt: str, original_task: str | None = None) -> dict[str, Any]:
        raise NotImplementedError
