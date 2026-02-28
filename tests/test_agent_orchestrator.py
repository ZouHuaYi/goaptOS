from gtos.agents import AgentOrchestrator, CoderAgent, MemoryAgent, PlannerAgent, ReviewerAgent
from gtos.core.event_bus import EventBus
from gtos.core.events import ActionPayload, EventName


class _LLM:
    def refine_task(self, task_prompt: str) -> str:
        return f"{task_prompt}\n# refined"

    def reflect_execution(self, task_prompt: str, result: dict, trace: list[dict]) -> str:
        return '{"task_type":"unit","failure_pattern":"","improved_prompt":"x","skill_template":"print(1)"}'


class _ReactLoop:
    def run(self, task: str, original_task: str | None = None) -> dict:
        return {"success": True, "task": original_task or task, "stdout": "ok", "fix_rounds": 0, "code": "print(1)"}


class _Memory:
    def __init__(self) -> None:
        self.calls = 0

    def add(self, text: str, metadata: dict | None = None) -> None:
        self.calls += 1


def test_orchestrator_planner_executor_reviewer_mode() -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(
        EventName.ON_ACTION,
        lambda event: seen.append(event.payload.type) if isinstance(event.payload, ActionPayload) else None,
    )

    orchestrator = AgentOrchestrator(
        planner=PlannerAgent(role="planner"),
        coder=CoderAgent(role="coder"),
        reviewer=ReviewerAgent(role="reviewer"),
        memory_agent=MemoryAgent(role="memory"),
        event_bus=bus,
    )
    mem = _Memory()
    result = orchestrator.execute(
        "task",
        mode="planner_executor_reviewer",
        context={"llm": _LLM(), "react_loop": _ReactLoop(), "memory": mem, "original_task": "task"},
    )
    assert result["success"] is True
    assert "agent_trace" in result
    assert mem.calls == 1
    assert "agent_plan" in seen
    assert "agent_review" in seen
    assert "agent_memory" in seen


def test_orchestrator_round_robin_mode() -> None:
    orchestrator = AgentOrchestrator(
        planner=PlannerAgent(role="planner"),
        coder=CoderAgent(role="coder"),
        reviewer=ReviewerAgent(role="reviewer"),
    )
    result = orchestrator.execute(
        "task",
        mode="round-robin",
        max_rounds=2,
        context={"llm": _LLM(), "react_loop": _ReactLoop(), "original_task": "task"},
    )
    assert result["success"] is True
    assert result.get("_agent_orchestration", {}).get("mode") == "round-robin"
