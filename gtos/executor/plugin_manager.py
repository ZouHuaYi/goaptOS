# gtos/executor/plugin_manager.py
"""插件注册与洋葱式调用。内层不感知插件，由调用方按顺序应用。"""

from typing import Any

from gtos.core.event_bus import EventBus
from gtos.core.interfaces.plugin import PluginLifecycle

class Plugin(PluginLifecycle):
    """Backward-compatible alias for unified plugin lifecycle interface."""


class PluginManager:
    """按注册顺序依次应用插件：pre 从外到内，post 从内到外。"""

    _CORE_EVENTS = (
        "on_task_start",
        "on_plan_generated",
        "on_thought",
        "on_action",
        "on_execution_success",
        "on_execution_failure",
        "on_reflection_complete",
        "on_task_end",
    )

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._plugins: list[Plugin] = []
        self._started = False
        self._event_bus = event_bus or EventBus()

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)
        for event_name in self._CORE_EVENTS:
            self._event_bus.subscribe(event_name, lambda payload, p=plugin, e=event_name: p.on_event(e, payload))
        if self._started:
            plugin.on_init({"plugins": len(self._plugins)})

    def start(self) -> None:
        if self._started:
            return
        for p in self._plugins:
            p.on_init({"plugins": len(self._plugins)})
        self._event_bus.emit("on_task_start", {"plugins": len(self._plugins)})
        self._started = True

    def shutdown(self) -> None:
        if not self._started:
            return
        self._event_bus.emit("on_task_end", {"plugins": len(self._plugins)})
        for p in reversed(self._plugins):
            p.on_shutdown()
        self._started = False

    def apply_pre_execute(self, task_prompt: str) -> str:
        for p in self._plugins:
            task_prompt = p.pre_execute(task_prompt)
        payload = self._event_bus.emit("on_action", {"type": "task_prompt", "task_prompt": task_prompt})
        return str(payload.get("task_prompt", task_prompt))

    def apply_post_execute(self, result: dict) -> dict:
        out = dict(result)
        for p in reversed(self._plugins):
            out = p.post_execute(out)
        payload = self._event_bus.emit("on_execution_success", {"result": out})
        out = payload.get("result", result)
        return out if isinstance(out, dict) else dict(result)

    def apply_on_error(self, error_info: Any) -> Any:
        normalized = error_info
        for p in self._plugins:
            normalized = p.on_error(normalized)
        payload = self._event_bus.emit("on_execution_failure", {"error_info": normalized})
        return payload.get("error_info", normalized)

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus
