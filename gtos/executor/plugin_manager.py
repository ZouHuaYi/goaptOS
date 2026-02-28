# gtos/executor/plugin_manager.py
"""Pure event-driven plugin manager."""

from typing import Any

from gtos.core.event_bus import EventBus
from gtos.core.events import (
    EventName,
    ExecutionFailurePayload,
    ExecutionSuccessPayload,
    TaskEndPayload,
    TaskPromptActionPayload,
    TaskStartPayload,
)
from gtos.core.interfaces.plugin import PluginLifecycle

class Plugin(PluginLifecycle):
    """Concrete plugin base alias."""


class PluginManager:
    """Plugin manager with explicit event pipeline."""

    _CORE_EVENTS = (
        EventName.ON_TASK_START,
        EventName.ON_PLAN_GENERATED,
        EventName.ON_THOUGHT,
        EventName.ON_ACTION,
        EventName.ON_EXECUTION_SUCCESS,
        EventName.ON_EXECUTION_FAILURE,
        EventName.ON_REFLECTION_COMPLETE,
        EventName.ON_TASK_END,
    )

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._plugins: list[Plugin] = []
        self._started = False
        self._event_bus = event_bus or EventBus()

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)
        for event_name in self._CORE_EVENTS:
            self._event_bus.subscribe(event_name, lambda event, p=plugin: p.on_event(event))
        if self._started:
            plugin.on_init({"plugins": len(self._plugins)})

    def start(self) -> None:
        if self._started:
            return
        for p in self._plugins:
            p.on_init({"plugins": len(self._plugins)})
        self._event_bus.emit_name(EventName.ON_TASK_START, TaskStartPayload(plugins=len(self._plugins)))
        self._started = True

    def shutdown(self) -> None:
        if not self._started:
            return
        self._event_bus.emit_name(EventName.ON_TASK_END, TaskEndPayload(plugins=len(self._plugins)))
        for p in reversed(self._plugins):
            p.on_shutdown()
        self._started = False

    def apply_pre_execute(self, task_prompt: str) -> str:
        event = self._event_bus.emit_name(EventName.ON_ACTION, TaskPromptActionPayload(task_prompt=task_prompt))
        return str(event.payload.task_prompt)

    def apply_post_execute(self, result: dict) -> dict:
        event = self._event_bus.emit_name(EventName.ON_EXECUTION_SUCCESS, ExecutionSuccessPayload(result=dict(result)))
        out = event.payload.result
        return out if isinstance(out, dict) else dict(result)

    def apply_on_error(self, error_info: Any) -> Any:
        event = self._event_bus.emit_name(EventName.ON_EXECUTION_FAILURE, ExecutionFailurePayload(error_info=error_info))
        return event.payload.error_info

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus
