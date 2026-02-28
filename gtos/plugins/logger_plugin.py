# gtos/plugins/logger_plugin.py
"""监控/日志插件：记录执行前后、耗时与错误。"""

import logging
import time
from gtos.core.events import EventName, ExecutionFailurePayload, ExecutionSuccessPayload, TaskPromptActionPayload
from gtos.core.interfaces.result import append_log, normalize_error
from gtos.executor.plugin_manager import Plugin

logger = logging.getLogger("gtos")


class LoggerPlugin(Plugin):
    def __init__(self) -> None:
        self._start_time: float | None = None

    def on_event(self, event) -> None:
        if event.name == EventName.ON_ACTION and isinstance(event.payload, TaskPromptActionPayload):
            task_prompt = str(event.payload.task_prompt or "")
            self._start_time = time.perf_counter()
            logger.info("pre_execute: task=%s", (task_prompt[:200] + "..." if len(task_prompt) > 200 else task_prompt))
            return
        if event.name == EventName.ON_EXECUTION_SUCCESS and isinstance(event.payload, ExecutionSuccessPayload):
            result = event.payload.result
            duration = (time.perf_counter() - self._start_time) * 1000 if self._start_time is not None else 0
            logger.info("post_execute: success=%s duration_ms=%.0f", result.get("success"), duration)
            event.payload.result = append_log(
                dict(result),
                level="info",
                event="plugin.logger.post_execute",
                message="logger plugin observed execution result",
                duration_ms=round(duration, 2),
                success=bool(result.get("success")),
            )
            return
        if event.name == EventName.ON_EXECUTION_FAILURE and isinstance(event.payload, ExecutionFailurePayload):
            normalized = normalize_error(event.payload.error_info, default_code="plugin_error", retriable=False)
            logger.warning("on_error: %s", str(normalized.get("message", ""))[:300])
            event.payload.error_info = normalized
