# gtos/executor/plugin_manager.py
"""插件注册与洋葱式调用。内层不感知插件，由调用方按顺序应用。"""

from typing import Any

from gtos.core.interfaces.plugin import PluginLifecycle

class Plugin(PluginLifecycle):
    """Backward-compatible alias for unified plugin lifecycle interface."""


class PluginManager:
    """按注册顺序依次应用插件：pre 从外到内，post 从内到外。"""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []
        self._started = False

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)
        if self._started:
            plugin.on_init({"plugins": len(self._plugins)})

    def start(self) -> None:
        if self._started:
            return
        for p in self._plugins:
            p.on_init({"plugins": len(self._plugins)})
        self._started = True

    def shutdown(self) -> None:
        if not self._started:
            return
        for p in reversed(self._plugins):
            p.on_shutdown()
        self._started = False

    def apply_pre_execute(self, task_prompt: str) -> str:
        for p in self._plugins:
            task_prompt = p.pre_execute(task_prompt)
        return task_prompt

    def apply_post_execute(self, result: dict) -> dict:
        for p in reversed(self._plugins):
            result = p.post_execute(result)
        return result

    def apply_on_error(self, error_info: Any) -> Any:
        for p in self._plugins:
            error_info = p.on_error(error_info)
        return error_info
