"""Agent orchestrator with multiple collaboration modes."""

from __future__ import annotations

from typing import Any

from gtos.agents.base_agent import BaseAgent


class AgentOrchestrator:
    def __init__(
        self,
        *,
        planner: BaseAgent,
        coder: BaseAgent,
        reviewer: BaseAgent,
        memory_agent: BaseAgent | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._planner = planner
        self._coder = coder
        self._reviewer = reviewer
        self._memory = memory_agent
        self._bus = event_bus

    def execute(
        self,
        task: str,
        *,
        mode: str = "planner_executor_reviewer",
        max_rounds: int = 2,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = dict(context or {})
        trace: list[dict[str, Any]] = []
        m = (mode or "planner_executor_reviewer").strip().lower()

        if m == "sequential" or m == "planner_executor_reviewer":
            result = self._run_planner_executor_reviewer(task, ctx, trace)
        elif m == "round-robin":
            result = self._run_round_robin(task, ctx, trace, max_rounds=max_rounds)
        elif m == "debate":
            result = self._run_debate(task, ctx, trace, max_rounds=max_rounds)
        else:
            result = self._run_planner_executor_reviewer(task, ctx, trace)

        if self._memory:
            mem = self._memory.act(task, {**ctx, "result": result})
            trace.append({"agent": self._memory.role, "phase": "act", "output": mem})
            self._emit("on_action", {"type": "agent_memory", "agent": self._memory.role, "output": mem})

        out = dict(result)
        out["agent_trace"] = trace
        out.setdefault("_agent_orchestration", {"mode": m, "rounds": max_rounds})
        return out

    def _run_planner_executor_reviewer(self, task: str, ctx: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
        planner_thought = self._planner.think(task, ctx)
        self._emit("on_thought", {"agent": self._planner.role, "thought": planner_thought, "task": task})
        plan = self._planner.act(task, ctx)
        trace.append({"agent": self._planner.role, "phase": "act", "output": plan})
        self._emit("on_action", {"type": "agent_plan", "agent": self._planner.role, "output": plan})

        refined_task = str(plan.get("refined_task", task) or task)
        code_result = self._coder.act(refined_task, {**ctx, "original_task": task})
        trace.append({"agent": self._coder.role, "phase": "act", "output": {"success": code_result.get("success"), "task": code_result.get("task", task)}})

        review = self._reviewer.act(task, {**ctx, "result": code_result})
        trace.append({"agent": self._reviewer.role, "phase": "act", "output": review})
        self._emit("on_action", {"type": "agent_review", "agent": self._reviewer.role, "output": review})
        code_result["_agent_review"] = review.get("review", {})
        return code_result

    def _run_round_robin(self, task: str, ctx: dict[str, Any], trace: list[dict[str, Any]], *, max_rounds: int) -> dict[str, Any]:
        current_task = task
        latest: dict[str, Any] = {"success": False, "task": task, "error": "round_robin_no_result"}
        for _ in range(max(1, int(max_rounds))):
            plan = self._planner.act(current_task, ctx)
            trace.append({"agent": self._planner.role, "phase": "act", "output": plan})
            current_task = str(plan.get("refined_task", current_task) or current_task)
            latest = self._coder.act(current_task, {**ctx, "original_task": task})
            trace.append({"agent": self._coder.role, "phase": "act", "output": {"success": latest.get("success")}})
            review = self._reviewer.act(task, {**ctx, "result": latest})
            trace.append({"agent": self._reviewer.role, "phase": "act", "output": review})
            approved = bool((review.get("review") or {}).get("approved", latest.get("success")))
            if approved:
                latest["_agent_review"] = review.get("review", {})
                return latest
        latest.setdefault("error", "round_robin_review_not_approved")
        return latest

    def _run_debate(self, task: str, ctx: dict[str, Any], trace: list[dict[str, Any]], *, max_rounds: int) -> dict[str, Any]:
        best: dict[str, Any] = {"success": False, "task": task, "error": "debate_no_result"}
        candidates: list[dict[str, Any]] = []
        for i in range(max(1, int(max_rounds))):
            candidate_task = f"{task}\n\n# candidate {i + 1}"
            result = self._coder.act(candidate_task, {**ctx, "original_task": task})
            trace.append({"agent": self._coder.role, "phase": f"candidate_{i + 1}", "output": {"success": result.get("success")}})
            candidates.append(result)
            if result.get("success") and not best.get("success"):
                best = result
        review = self._reviewer.act(task, {**ctx, "result": best, "candidates": candidates})
        trace.append({"agent": self._reviewer.role, "phase": "act", "output": review})
        best["_agent_review"] = review.get("review", {})
        return best

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self._bus and hasattr(self._bus, "emit"):
            self._bus.emit(event_name, payload)

