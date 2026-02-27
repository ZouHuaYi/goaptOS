# gtos/executor/plugin_manager.py
"""插件注册与洋葱式调用。内层不感知插件，由调用方按顺序应用。"""

from abc import ABC, abstractmethod
from typing import Any


class Plugin(ABC):
    """插件基类：pre → 执行 → post；出错时 on_error。"""

    def pre_execute(self, task_prompt: str) -> str:
        """代码生成前处理输入。"""
        return task_prompt

    def post_execute(self, result: dict) -> dict:
        """代码执行完成后处理结果。"""
        return result

    def on_error(self, error_info: str) -> str:
        """执行错误时处理（可返回修正后的提示或记录）。"""
        return error_info


class PluginManager:
    """按注册顺序依次应用插件：pre 从外到内，post 从内到外。"""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)

    def apply_pre_execute(self, task_prompt: str) -> str:
        for p in self._plugins:
            task_prompt = p.pre_execute(task_prompt)
        return task_prompt

    def apply_post_execute(self, result: dict) -> dict:
        for p in reversed(self._plugins):
            result = p.post_execute(result)
        return result

    def apply_on_error(self, error_info: str) -> str:
        for p in self._plugins:
            error_info = p.on_error(error_info)
        return error_info
