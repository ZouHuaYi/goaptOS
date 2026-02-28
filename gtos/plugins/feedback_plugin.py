"""Feedback plugin: log per-run metrics for self-optimization."""

import threading
import time

from gtos.core.events import EventName, ExecutionFailurePayload, ExecutionSuccessPayload, TaskPromptActionPayload
from gtos.analytics.run_logger import RunLogger
from gtos.core.interfaces.result import append_log, normalize_error
from gtos.executor.plugin_manager import Plugin


class FeedbackPlugin(Plugin):
    def __init__(self, run_logger: RunLogger) -> None:
        self._run_logger = run_logger
        self._local = threading.local()

    def on_event(self, event) -> None:
        if event.name == EventName.ON_ACTION and isinstance(event.payload, TaskPromptActionPayload):
            task_prompt = str(event.payload.task_prompt or "")
            self._local.start = time.perf_counter()
            self._local.run_id = self._run_logger.start_run(task_prompt, task_prompt, meta={"phase": "pre_execute", "level": "node"})
            return
        if event.name == EventName.ON_EXECUTION_SUCCESS and isinstance(event.payload, ExecutionSuccessPayload):
            result = event.payload.result
            start = getattr(self._local, "start", None)
            run_id = getattr(self._local, "run_id", "")
            latency_ms = (time.perf_counter() - start) * 1000 if start is not None else 0.0
            out = dict(result)
            out.setdefault("_metrics", {})["latency_ms"] = round(latency_ms, 2)
            out = append_log(
                out,
                level="info",
                event="plugin.feedback.post_execute",
                message="feedback plugin persisted node run metrics",
                run_id=run_id,
                latency_ms=round(latency_ms, 2),
            )
            if run_id:
                self._run_logger.finish_run(run_id, out, level="node")
            event.payload.result = out
            return
        if event.name == EventName.ON_EXECUTION_FAILURE and isinstance(event.payload, ExecutionFailurePayload):
            normalized = normalize_error(event.payload.error_info, default_code="execution_exception", retriable=False)
            run_id = getattr(self._local, "run_id", "")
            if run_id:
                self._run_logger.finish_run(
                    run_id,
                    {"success": False, "error": normalized.get("message", ""), "_error": normalized, "_metrics": {"latency_ms": 0.0}, "fix_rounds": 0},
                    error_type="exception",
                    level="node",
                )
            event.payload.error_info = normalized
