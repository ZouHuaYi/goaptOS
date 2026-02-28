"""Task-level checkpoint, rollback, and retry metadata manager."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any


class TaskTransactionManager:
    def __init__(self, run_id: str, base_dir: str | Path = "data/checkpoints") -> None:
        self.run_id = run_id
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._base_dir / f"{run_id}.json"
        self._data: dict[str, Any] = {"run_id": run_id, "created_ts": time(), "tasks": {}}
        self._save()

    @property
    def path(self) -> str:
        return str(self._path)

    def create_checkpoint(self, task_id: str, payload: dict[str, Any]) -> str:
        entry = self._task(task_id)
        checkpoint_id = f"{task_id}-{int(time() * 1000)}"
        entry["checkpoint"] = {
            "id": checkpoint_id,
            "payload": payload,
            "created_ts": time(),
        }
        entry.setdefault("attempts", [])
        entry["rolled_back"] = False
        self._save()
        return checkpoint_id

    def record_attempt(self, task_id: str, attempt: int, success: bool, error: str = "") -> None:
        entry = self._task(task_id)
        entry.setdefault("attempts", []).append(
            {
                "attempt": attempt,
                "success": bool(success),
                "error": error,
                "ts": time(),
            }
        )
        self._save()

    def rollback(self, task_id: str, reason: str) -> None:
        entry = self._task(task_id)
        entry["rolled_back"] = True
        entry["rollback_reason"] = reason
        entry["rollback_ts"] = time()
        self._save()

    def finish_task(self, task_id: str, success: bool, meta: dict[str, Any] | None = None) -> None:
        entry = self._task(task_id)
        entry["success"] = bool(success)
        entry["finished_ts"] = time()
        if meta:
            entry["meta"] = meta
        self._save()

    def get_task(self, task_id: str) -> dict[str, Any]:
        return dict(self._data.get("tasks", {}).get(task_id, {}))

    def _task(self, task_id: str) -> dict[str, Any]:
        tasks = self._data.setdefault("tasks", {})
        if task_id not in tasks:
            tasks[task_id] = {"task_id": task_id, "created_ts": time(), "attempts": []}
        return tasks[task_id]

    def _save(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        tmp.replace(self._path)
