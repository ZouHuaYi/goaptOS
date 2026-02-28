"""Default implementations for planner/coder/reviewer/memory agents."""

from __future__ import annotations

import json
from typing import Any

from gtos.agents.base_agent import BaseAgent


class PlannerAgent(BaseAgent):
    def think(self, task: str, context: dict[str, Any]) -> str:
        return "refine_task"

    def act(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        llm = context.get("llm")
        refined = task
        if llm is not None and hasattr(llm, "refine_task"):
            try:
                refined = str(llm.refine_task(task) or task)
            except Exception:
                refined = task
        return {"success": True, "task": task, "refined_task": refined}


class CoderAgent(BaseAgent):
    def think(self, task: str, context: dict[str, Any]) -> str:
        return "execute_task"

    def act(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        react_loop = context.get("react_loop")
        code_executor = context.get("code_executor")
        original_task = context.get("original_task") or task
        if react_loop is not None:
            result = react_loop.run(task, original_task=original_task)
            return result if isinstance(result, dict) else {"success": False, "error": "react_loop_invalid_result"}
        if code_executor is not None:
            result = code_executor.execute_task(task, original_task=original_task)
            return result if isinstance(result, dict) else {"success": False, "error": "code_executor_invalid_result"}
        return {"success": False, "task": original_task, "error": "no_executor"}


class ReviewerAgent(BaseAgent):
    def think(self, task: str, context: dict[str, Any]) -> str:
        return "review_result"

    def act(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        llm = context.get("llm")
        result = context.get("result") if isinstance(context.get("result"), dict) else {}
        review = {"approved": bool(result.get("success")), "summary": "rule_based"}
        if llm is not None and hasattr(llm, "reflect_execution"):
            try:
                raw = str(llm.reflect_execution(task, result, result.get("react_trace", [])) or "").strip()
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    review = {
                        "approved": bool(result.get("success")),
                        "summary": "llm_reflection",
                        "reflection": parsed,
                    }
            except Exception:
                pass
        return {"success": True, "task": task, "review": review}


class MemoryAgent(BaseAgent):
    def think(self, task: str, context: dict[str, Any]) -> str:
        return "capture_memory"

    def act(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        memory = context.get("memory")
        memory_manager = context.get("memory_manager")
        result = context.get("result") if isinstance(context.get("result"), dict) else {}
        if memory_manager is not None:
            try:
                memory_manager.write_episode(task, result, payload={"source": "memory_agent"})
                summary = (
                    f"task={task[:200]} "
                    f"success={bool(result.get('success'))} "
                    f"fix_rounds={int(result.get('fix_rounds', 0) or 0)}"
                )
                memory_manager.write_semantic(summary, tags={"source": "memory_agent"}, source="memory_agent")
                return {"success": True, "task": task, "memory_written": True}
            except Exception:
                return {"success": False, "task": task, "memory_written": False}
        if memory is None:
            return {"success": True, "task": task, "memory_written": False}
        try:
            if hasattr(memory, "add"):
                memory.add(f"task: {task}\nsuccess: {bool(result.get('success'))}", metadata={"source": "memory_agent"})
            return {"success": True, "task": task, "memory_written": True}
        except Exception:
            return {"success": False, "task": task, "memory_written": False}
