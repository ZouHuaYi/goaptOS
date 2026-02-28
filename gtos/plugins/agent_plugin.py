# gtos/plugins/agent_plugin.py
"""多任务/Agent 插件：预留并行与 DAG 扩展。当前仅透传。"""

from gtos.core.interfaces.result import normalize_error
from gtos.executor.plugin_manager import Plugin


class AgentPlugin(Plugin):
    def pre_execute(self, task_prompt: str) -> str:
        return task_prompt

    def post_execute(self, result: dict) -> dict:
        return result

    def on_error(self, error_info: object) -> object:
        return normalize_error(error_info, default_code="agent_error", retriable=False)
