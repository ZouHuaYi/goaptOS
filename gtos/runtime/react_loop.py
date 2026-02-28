"""ReAct runtime loop: Thought -> Action -> Observation."""

from __future__ import annotations

import json
import re
from typing import Any

from gtos.core.event_bus import EventBus
from gtos.core.events import (
    ActionPayload,
    EventName,
    ExecutionFailurePayload,
    ExecutionSuccessPayload,
    ThoughtPayload,
)
from gtos.runtime.action_schema import parse_action


class ReActLoop:
    def __init__(
        self,
        *,
        llm: Any,
        code_executor: Any,
        capabilities: Any | None = None,
        event_bus: EventBus | None = None,
        max_steps: int = 6,
        tool_catalog_max_items: int = 12,
        tool_catalog_max_chars: int = 2400,
        tool_preference: dict[str, int] | None = None,
    ) -> None:
        self._llm = llm
        self._executor = code_executor
        self._capabilities = capabilities
        self._bus = event_bus or EventBus()
        self._max_steps = max(1, int(max_steps))
        self._tool_catalog_max_items = max(1, int(tool_catalog_max_items))
        self._tool_catalog_max_chars = max(300, int(tool_catalog_max_chars))
        self._tool_preference = {str(k): int(v) for k, v in (tool_preference or {}).items() if str(k).strip()}

    def run(self, task: str, original_task: str | None = None) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        canonical_task = (original_task or task).strip()
        final_result: dict[str, Any] = {"success": False, "task": canonical_task, "error": "react loop exited unexpectedly"}

        for step in range(1, self._max_steps + 1):
            thought = self._think(task=task, history=history)
            self._bus.emit_name(EventName.ON_THOUGHT, ThoughtPayload(step=step, task=canonical_task, thought=thought))

            action = parse_action(thought)
            self._bus.emit_name(EventName.ON_ACTION, ActionPayload(step=step, task=canonical_task, action=action))

            observation = self._execute_action(action=action, task=task, original_task=canonical_task)
            success = bool(observation.get("success"))
            if success:
                self._bus.emit_name(
                    EventName.ON_EXECUTION_SUCCESS,
                    ExecutionSuccessPayload(step=step, task=canonical_task, result=observation),
                )
            else:
                self._bus.emit_name(
                    EventName.ON_EXECUTION_FAILURE,
                    ExecutionFailurePayload(step=step, task=canonical_task, error_info=observation.get("error", "")),
                )

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
            enriched_task = self._inject_tool_catalog(task)
            return str(thinker(enriched_task, history) or "")
        if not history:
            return '{"type":"code_exec","language":"python","content":""}'
        return '{"type":"finish","result":{"success":false,"error":"react_step_not_supported"}}'

    def _inject_tool_catalog(self, task: str) -> str:
        if self._capabilities is None or not hasattr(self._capabilities, "list_tools"):
            return task
        try:
            tools = self._capabilities.list_tools()
        except Exception:
            return task
        if not isinstance(tools, list) or not tools:
            return task
        scored: list[tuple[float, str]] = []
        task_tokens = self._tokens(task)
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name", "") or "").strip()
            if not name:
                continue
            desc = str(t.get("description", "") or "").strip()
            schema = t.get("input_schema", {}) if isinstance(t.get("input_schema", {}), dict) else {}
            constraints = t.get("constraints", {}) if isinstance(t.get("constraints", {}), dict) else {}
            props = schema.get("properties", {}) if isinstance(schema.get("properties", {}), dict) else {}
            args = ", ".join(list(props.keys())[:6])
            row = f"- {name}" + (f" | {desc[:80]}" if desc else "") + (f" | args: {args}" if args else "")
            tool_text = " ".join([name, desc, " ".join(list(props.keys()))])
            score = self._relevance_score(task_tokens, self._tokens(tool_text))
            score += self._preference_boost(name)
            score += self._permission_priority_boost(task_tokens, constraints)
            scored.append((score, row))
        scored.sort(key=lambda x: (-x[0], x[1]))
        rows = [r for _, r in scored[: self._tool_catalog_max_items]]
        if not rows:
            return task
        block = "[Available Tools]\nUse exact tool name in tool_call.name.\n" + "\n".join(rows)
        out = f"{task}\n\n{block}"
        if len(out) <= self._tool_catalog_max_chars:
            return out
        trimmed = "\n".join(rows[:4])
        return f"{task}\n\n[Available Tools]\nUse exact tool name in tool_call.name.\n{trimmed}"

    def _tokens(self, text: str) -> set[str]:
        raw = re.findall(r"[a-zA-Z0-9_:-]+|[\u4e00-\u9fff]{2,}", str(text or "").lower())
        generic = {
            "tool",
            "tools",
            "call",
            "args",
            "type",
            "name",
            "with",
            "and",
            "the",
            "use",
            "using",
            "please",
            "mcp",
            "工具",
            "调用",
            "使用",
            "参数",
        }
        return {x for x in raw if len(x) >= 2 and x not in generic}

    def _relevance_score(self, task_tokens: set[str], tool_tokens: set[str]) -> float:
        if not task_tokens or not tool_tokens:
            return 0.0
        inter = len(task_tokens & tool_tokens)
        return inter / max(1, len(task_tokens))

    def _preference_boost(self, tool_name: str) -> float:
        c = int(self._tool_preference.get(str(tool_name), 0))
        if c <= 0:
            return 0.0
        return min(0.25, 0.03 * c)

    def _permission_priority_boost(self, task_tokens: set[str], constraints: dict[str, Any]) -> float:
        actions = constraints.get("allowed_actions", [])
        if not isinstance(actions, list) or not actions:
            return 0.0
        action_tokens = self._tokens(" ".join([str(x) for x in actions]))
        if not action_tokens:
            return 0.0
        overlap = len(task_tokens & action_tokens)
        if overlap <= 0:
            return 0.0
        return min(0.2, 0.08 * overlap)

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

        if action_type == "tool_call":
            tool_name = str(action.get("name", "") or "").strip()
            params = action.get("arguments", {})
            if not isinstance(params, dict):
                params = {}
            if not tool_name:
                obs = {
                    "success": False,
                    "task": original_task,
                    "error": "tool_call_missing_name",
                    "_react_action": action,
                }
                return {"done": False, "success": False, **obs}
            if self._capabilities is None or not hasattr(self._capabilities, "execute"):
                obs = {
                    "success": False,
                    "task": original_task,
                    "error": "capability_registry_unavailable",
                    "_react_action": action,
                }
                return {"done": False, "success": False, **obs}
            try:
                tool_result = self._capabilities.execute(tool_name, params)
                compact_result = tool_result
                try:
                    raw = json.dumps(tool_result, ensure_ascii=False)
                    if len(raw) > 2000:
                        compact_result = {"truncated": True, "preview": raw[:2000]}
                except Exception:
                    compact_result = str(tool_result)[:2000]
                obs = {
                    "success": True,
                    "task": original_task,
                    "stdout": f"tool_call_ok: {tool_name}",
                    "_tool_result": compact_result,
                    "_observation": {
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "ok": True,
                        "data": compact_result,
                    },
                    "_react_action": action,
                }
                return {"done": False, "success": True, **obs}
            except Exception as e:
                obs = {
                    "success": False,
                    "task": original_task,
                    "error": f"tool_call_failed: {e}",
                    "_observation": {
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "ok": False,
                        "error": str(e)[:400],
                    },
                    "_react_action": action,
                }
                return {"done": False, "success": False, **obs}

        # Placeholder for future action types.
        obs = {
            "success": False,
            "task": original_task,
            "error": f"unsupported action type: {action_type}",
            "_react_action": action,
        }
        return {"done": False, "success": False, **obs}
