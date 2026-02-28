"""Unified plugin lifecycle interface."""

from __future__ import annotations

from abc import ABC
from typing import Any

from gtos.core.events import RuntimeEvent


class PluginLifecycle(ABC):
    """Plugin lifecycle: init -> event handling -> shutdown."""

    def on_init(self, context: dict[str, Any] | None = None) -> None:
        return None

    def on_event(self, event: RuntimeEvent) -> None:
        return None

    def on_shutdown(self) -> None:
        return None
