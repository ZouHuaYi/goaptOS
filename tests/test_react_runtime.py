from pathlib import Path
import time

from gtos.core.events import EventName
from gtos.memory.memory_manager import MemoryManager
from gtos.core.event_bus import EventBus
from gtos.runtime import ReflectionEngine, ReActLoop, parse_action


class _StubLLM:
    def __init__(self) -> None:
        self.calls = 0

    def react_step(self, task_prompt: str, history: list[dict]) -> str:
        self.calls += 1
        if self.calls == 1:
            return '{"type":"code_exec","language":"python","content":"print(1+2)"}'
        return '{"type":"finish","result":{"success":false,"error":"should_not_reach"}}'

    def reflect_execution(self, task_prompt: str, result: dict, trace: list[dict]) -> str:
        return (
            '{"task_type":"unit","failure_pattern":"","improved_prompt":"'
            + task_prompt
            + '","skill_template":"print(1+2)"}'
        )


class _StubExecutor:
    def execute_task(self, task_prompt: str, original_task: str | None = None) -> dict:
        return {
            "success": True,
            "task": original_task or task_prompt,
            "stdout": "3\n",
            "stderr": "",
            "fix_rounds": 0,
            "code": "print(1+2)",
        }


class _SkillStore:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def add(self, task: str, code: str, success: bool = True, metadata: dict | None = None) -> None:
        self.records.append({"task": task, "code": code, "success": success, "metadata": metadata or {}})


class _VectorStore:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, text: str, metadata: dict | None = None) -> None:
        self.items.append({"text": text, "metadata": metadata or {}})


def test_parse_action_fallback_to_code_exec() -> None:
    out = parse_action("print('x')")
    assert out["type"] == "code_exec"
    assert out["content"] == "print('x')"


def test_react_loop_runs_until_success() -> None:
    events: list[str] = []
    bus = EventBus()
    bus.subscribe(EventName.ON_THOUGHT, lambda event: events.append("thought"))
    bus.subscribe(EventName.ON_ACTION, lambda event: events.append("action"))
    bus.subscribe(EventName.ON_EXECUTION_SUCCESS, lambda event: events.append("success"))
    loop = ReActLoop(llm=_StubLLM(), code_executor=_StubExecutor(), event_bus=bus, max_steps=3)
    result = loop.run("compute 1+2")
    assert result["success"] is True
    assert result["stdout"].strip() == "3"
    assert len(result.get("react_trace", [])) == 1
    assert events == ["thought", "action", "success"]


def test_reflection_engine_persists_and_writes_memory(tmp_path: Path) -> None:
    skill_store = _SkillStore()
    vector_store = _VectorStore()
    out_file = tmp_path / "reflections.jsonl"
    engine = ReflectionEngine(
        llm=_StubLLM(),
        output_file=out_file,
        skill_store=skill_store,
        vector_store=vector_store,
    )
    reflection = engine.reflect(
        task="compute 1+2",
        result={"success": True, "code": "print(1+2)", "fix_rounds": 0},
        trace=[],
    )
    assert reflection["task_type"] == "unit"
    assert out_file.exists()
    assert len(skill_store.records) == 1
    assert len(vector_store.items) == 1


def test_reflection_engine_with_memory_manager() -> None:
    suffix = int(time.time() * 1000)
    db = Path(f"data/_unit_reflection_mm_{suffix}.db")
    out_file = Path(f"data/_unit_reflection_mm_{suffix}.jsonl")

    skill_store = _SkillStore()
    vector_store = _VectorStore()
    mm = MemoryManager(sqlite_db=db, vector_store=vector_store, skill_store=skill_store)
    engine = ReflectionEngine(
        llm=_StubLLM(),
        output_file=out_file,
        memory_manager=mm,
    )
    reflection = engine.reflect(
        task="compute 1+2",
        result={"success": False, "error": "ModuleNotFoundError: No module named 'pandas'", "fix_rounds": 1},
        trace=[],
    )
    q = mm.query("pandas", top_k=10)
    assert reflection["task_type"] == "unit"
    assert out_file.exists()
    assert len(q["episodic"]) >= 1
