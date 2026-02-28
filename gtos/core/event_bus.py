"""Simple in-process event bus for runtime and plugin decoupling."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger("gtos")

EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    """Event bus with best-effort dispatch.

    Handlers receive a mutable payload dict. Handler errors are logged and do not
    interrupt the remaining subscribers.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        if not event_name or not callable(handler):
            return
        self._handlers[event_name].append(handler)

    def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data: dict[str, Any] = payload if isinstance(payload, dict) else {}
        for handler in list(self._handlers.get(event_name, [])):
            try:
                handler(data)
            except Exception as e:
                logger.warning("event handler failed: event=%s err=%s", event_name, str(e)[:280])
        return data

