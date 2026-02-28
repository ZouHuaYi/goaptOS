"""Typed in-process event bus for runtime and plugin decoupling."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from gtos.core.events import EventName, EventPayload, RuntimeEvent

logger = logging.getLogger("gtos")

EventHandler = Callable[[RuntimeEvent], None]


class EventBus:
    """Event bus with best-effort dispatch.

    Handlers receive a mutable RuntimeEvent. Handler errors are logged and do not
    interrupt the remaining subscribers.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: EventName, handler: EventHandler) -> None:
        if not event_name or not callable(handler):
            return
        self._handlers[event_name].append(handler)

    def emit(self, event: RuntimeEvent) -> RuntimeEvent:
        for handler in list(self._handlers.get(event.name, [])):
            try:
                handler(event)
            except Exception as e:
                logger.warning("event handler failed: event=%s err=%s", event.name.value, str(e)[:280])
        return event

    def emit_name(self, name: EventName, payload: EventPayload) -> RuntimeEvent:
        return self.emit(RuntimeEvent(name=name, payload=payload))
