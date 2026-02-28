from pathlib import Path
import time

from gtos.memory.memory_manager import MemoryManager


class _VectorStore:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, text: str, metadata: dict | None = None) -> None:
        self.items.append({"text": text, "metadata": metadata or {}})

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        return [{"text": x["text"], "metadata": x["metadata"]} for x in self.items[:top_k]]


class _SkillStore:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, task: str, code: str, success: bool = True, metadata: dict | None = None) -> None:
        self.items.append({"task": task, "code": code, "success": success, "metadata": metadata or {}})


def _unique_db(name: str) -> Path:
    return Path(f"data/{name}_{int(time.time() * 1000)}.db")


def test_memory_manager_write_and_query() -> None:
    db = _unique_db("_unit_memory_manager")
    vector = _VectorStore()
    skills = _SkillStore()
    mm = MemoryManager(sqlite_db=db, vector_store=vector, skill_store=skills)

    mm.write_episode("task1", {"success": True, "fix_rounds": 0, "stdout": "ok"})
    mm.write_semantic("use retry when flaky", tags={"pattern": "retry"}, source="unit")
    mm.write_skill("task1", "print('ok')", success=True)

    out = mm.query("retry", top_k=3)
    assert len(out["semantic"]) >= 1
    assert len(skills.items) == 1
    assert len(vector.items) >= 1


def test_memory_manager_auto_abstract_missing_dependency() -> None:
    db = _unique_db("_unit_memory_manager_auto")
    mm = MemoryManager(sqlite_db=db, vector_store=_VectorStore(), skill_store=_SkillStore())

    err = "ModuleNotFoundError: No module named 'pandas'"
    mm.write_episode("task import pandas", {"success": False, "error": err, "fix_rounds": 1})
    mm.write_episode("task import pandas again", {"success": False, "error": err, "fix_rounds": 1})

    out = mm.query("dependency", top_k=10)
    text = " ".join([str(x.get("summary", "")) for x in out["semantic"]])
    assert "dependency" in text.lower() or "import" in text.lower()
