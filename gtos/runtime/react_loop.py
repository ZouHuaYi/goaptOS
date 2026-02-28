"""ReAct runtime loop: Thought -> Action -> Observation."""

from __future__ import annotations

from typing import Any

from gtos.core.event_bus import EventBus
from gtos.runtime.action_schema import parse_action


class ReActLoop:
    def __init__(
        self,
        *,
        llm: Any,
        code_executor: Any,
        event_bus: EventBus | None = None,
        max_steps: int = 6,
    ) -> None:
        self._llm = llm
        self._executor = code_executor
        self._bus = event_bus or EventBus()
        self._max_steps = max(1, int(max_steps))

    def run(self, task: str, original_task: str | None = None) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        canonical_task = (original_task or task).strip()
        final_result: dict[str, Any] = {"success": False, "task": canonical_task, "error": "react loop exited unexpectedly"}

        for step in range(1, self._max_steps + 1):
            thought = self._think(task=task, history=history)
            self._bus.emit("on_thought", {"step": step, "task": canonical_task, "thought": thought})

            action = parse_action(thought)
            self._bus.emit("on_action", {"step": step, "task": canonical_task, "action": action})

            observation = self._execute_action(action=action, task=task, original_task=canonical_task)
            success = bool(observation.get("success"))
            if success:
                self._bus.emit("on_execution_success", {"step": step, "task": canonical_task, "result": observation})
            else:
                self._bus.emit("on_execution_failure", {"step": step, "task": canonical_task, "error_info": observation.get("error", "")})

            history.append({"step": step, "thought": thought, "action": action, "observation": observation})
            final_result = observation.get("result", {}) if action.get("type") == "finish" else observation
            if observation.get("done"):
                break

        final_result = dict(final_result)
        final_result["react_trace"] = history
        final_result.setdefault("task", canonical_task)
        if not history:
            final_result.setdefault("success", False)
            final_result.setdefault("error", "no react steps executed")
        return final_result

    def _think(self, *, task: str, history: list[dict[str, Any]]) -> str:
        thinker = getattr(self._llm, "react_step", None)
        if callable(thinker):
            return str(thinker(task, history) or "")
        if not history:
            return '{"type":"code_exec","language":"python","content":""}'
        return '{"type":"finish","result":{"success":false,"error":"react_step_not_supported"}}'

    def _execute_action(self, *, action: dict[str, Any], task: str, original_task: str) -> dict[str, Any]:
        action_type = str(action.get("type", "code_exec"))
        if action_type == "finish":
            result = action.get("result", {})
            if not isinstance(result, dict):
                result = {"success": False, "error": "invalid finish result"}
            result.setdefault("task", original_task)
            return {"done": True, "success": bool(result.get("success")), "result": result}

        if action_type == "code_exec":
            prompt = str(action.get("content", "") or task)
            result = self._executor.execute_task(prompt, original_task=original_task)
            result = dict(result)
            result.setdefault("_react_action", action)
            return {"done": bool(result.get("success")), "success": bool(result.get("success")), **result}

        # Placeholder for future action types.
        obs = {
            "success": False,
            "task": original_task,
            "error": f"unsupported action type: {action_type}",
            "_react_action": action,
        }
        return {"done": False, "success": False, **obs}

