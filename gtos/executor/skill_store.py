# gtos/executor/skill_store.py
"""成功流程/技能存储。最小实现：JSON 文件。"""

import json
from pathlib import Path
from typing import Any


def _default_skills_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "skills.json"


class SkillStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _default_skills_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._skills: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._skills, f, ensure_ascii=False, indent=2)

    def add(self, task: str, code: str, success: bool = True) -> None:
        self._skills.append({"task": task, "code": code, "success": success})
        self._save()

    def get_recent(self, n: int = 5) -> list[dict[str, Any]]:
        return self._skills[-n:] if self._skills else []

    def search_by_task(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        return [s for s in self._skills if q in s.get("task", "").lower()]

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._skills)
