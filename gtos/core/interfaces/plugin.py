"""Unified plugin lifecycle interface."""

from __future__ import annotations

from abc import ABC
from typing import Any


class PluginLifecycle(ABC):
    """Plugin lifecycle: init -> pre_execute -> post_execute -> shutdown."""

    def on_init(self, context: dict[str, Any] | None = None) -> None:
        return None

    def pre_execute(self, task_prompt: str) -> str:
        return task_prompt

    def post_execute(self, result: dict[str, Any]) -> dict[str, Any]:
        return result

    def on_error(self, error_info: Any) -> Any:
        return error_info

    def on_event(self, event_name: str, payload: dict[str, Any]) -> None:
        return None

    def on_shutdown(self) -> None:
        return None
