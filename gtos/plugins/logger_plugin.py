# gtos/plugins/logger_plugin.py
"""监控/日志插件：记录执行前后、耗时与错误。"""

import logging
import time
from gtos.executor.plugin_manager import Plugin

logger = logging.getLogger("gtos")


class LoggerPlugin(Plugin):
    def __init__(self) -> None:
        self._start_time: float | None = None

    def pre_execute(self, task_prompt: str) -> str:
        self._start_time = time.perf_counter()
        logger.info("pre_execute: task=%s", (task_prompt[:200] + "..." if len(task_prompt) > 200 else task_prompt))
        return task_prompt

    def post_execute(self, result: dict) -> dict:
        duration = (time.perf_counter() - self._start_time) * 1000 if self._start_time is not None else 0
        logger.info("post_execute: success=%s duration_ms=%.0f", result.get("success"), duration)
        out = dict(result)
        out.setdefault("_log", {})["duration_ms"] = round(duration, 2)
        return out

    def on_error(self, error_info: str) -> str:
        logger.warning("on_error: %s", error_info[:300])
        return error_info
