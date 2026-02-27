"""Feedback plugin: log per-run metrics for self-optimization."""

import threading
import time

from gtos.analytics.run_logger import RunLogger
from gtos.executor.plugin_manager import Plugin


class FeedbackPlugin(Plugin):
    def __init__(self, run_logger: RunLogger) -> None:
        self._run_logger = run_logger
        self._local = threading.local()

    def pre_execute(self, task_prompt: str) -> str:
        start = time.perf_counter()
        run_id = self._run_logger.start_run(task_prompt, task_prompt, meta={"phase": "pre_execute", "level": "node"})
        self._local.start = start
        self._local.run_id = run_id
        return task_prompt

    def post_execute(self, result: dict) -> dict:
        out = dict(result)
        start = getattr(self._local, "start", None)
        run_id = getattr(self._local, "run_id", "")
        latency_ms = (time.perf_counter() - start) * 1000 if start is not None else 0.0
        out.setdefault("_metrics", {})["latency_ms"] = round(latency_ms, 2)
        if run_id:
            self._run_logger.finish_run(run_id, out, level="node")
        return out

    def on_error(self, error_info: str) -> str:
        run_id = getattr(self._local, "run_id", "")
        if run_id:
            self._run_logger.finish_run(
                run_id,
                {"success": False, "error": error_info, "_metrics": {"latency_ms": 0.0}, "fix_rounds": 0},
                error_type="exception",
                level="node",
            )
        return error_info
