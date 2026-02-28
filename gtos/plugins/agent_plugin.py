# gtos/plugins/agent_plugin.py
"""多任务/Agent 插件：预留并行与 DAG 扩展。当前仅透传。"""

from gtos.core.events import EventName, ExecutionFailurePayload
from gtos.core.interfaces.result import normalize_error
from gtos.executor.plugin_manager import Plugin


class AgentPlugin(Plugin):
    def on_event(self, event) -> None:
        if event.name == EventName.ON_EXECUTION_FAILURE and isinstance(event.payload, ExecutionFailurePayload):
            event.payload.error_info = normalize_error(event.payload.error_info, default_code="agent_error", retriable=False)
