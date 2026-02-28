"""Post-run reflection module for structured self-improvement signals."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ReflectionEngine:
    def __init__(
        self,
        *,
        llm: Any,
        output_file: str | Path,
        skill_store: Any | None = None,
        vector_store: Any | None = None,
        memory_manager: Any | None = None,
    ) -> None:
        self._llm = llm
        self._output_file = Path(output_file)
        self._output_file.parent.mkdir(parents=True, exist_ok=True)
        self._skill_store = skill_store
        self._vector_store = vector_store
        self._memory_manager = memory_manager

    def reflect(self, task: str, result: dict[str, Any], trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        reflection = self._from_llm(task, result, trace or []) or self._fallback(task, result)
        reflection = self._normalize(reflection)
        self._persist(task=task, result=result, reflection=reflection)
        self._write_memory(task=task, result=result, reflection=reflection)
        return reflection

    def _from_llm(self, task: str, result: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any] | None:
        reflector = getattr(self._llm, "reflect_execution", None)
        if not callable(reflector):
            return None
        raw = str(reflector(task, result, trace) or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _fallback(self, task: str, result: dict[str, Any]) -> dict[str, Any]:
        success = bool(result.get("success"))
        error = str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "")
        fix_rounds = int(result.get("fix_rounds", 0) or 0)
        task_type = "code_generation"
        failure_pattern = "" if success else (error[:280] or "execution_failure")
        improved_prompt = f"{task}\n\n约束：输出可直接运行的 Python 代码，并覆盖异常处理。".strip()
        skill_template = ""
        if success:
            code = str(result.get("code", "") or "")
            if code.strip():
                skill_template = code[:4000]
        return {
            "task_type": task_type,
            "failure_pattern": failure_pattern,
            "improved_prompt": improved_prompt,
            "skill_template": skill_template,
            "summary": {"success": success, "fix_rounds": fix_rounds},
        }

    def _normalize(self, obj: dict[str, Any]) -> dict[str, Any]:
        out = dict(obj or {})
        out.setdefault("task_type", "")
        out.setdefault("failure_pattern", "")
        out.setdefault("improved_prompt", "")
        out.setdefault("skill_template", "")
        return out

    def _persist(self, *, task: str, result: dict[str, Any], reflection: dict[str, Any]) -> None:
        record = {
            "ts": time.time(),
            "task": task,
            "success": bool(result.get("success")),
            "fix_rounds": int(result.get("fix_rounds", 0) or 0),
            "reflection": reflection,
        }
        with open(self._output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_memory(self, *, task: str, result: dict[str, Any], reflection: dict[str, Any]) -> None:
        if self._memory_manager is not None:
            try:
                self._memory_manager.write_episode(task, result, payload={"source": "reflection"})
                self._memory_manager.write_semantic(
                    summary="\n".join(
                        [
                            f"task_type: {reflection.get('task_type', '')}",
                            f"failure_pattern: {reflection.get('failure_pattern', '')}",
                            f"improved_prompt: {reflection.get('improved_prompt', '')[:1000]}",
                        ]
                    ),
                    tags={"source": "reflection", "task": task[:180]},
                    source="reflection",
                )
                self._memory_manager.write_skill(
                    task=f"[reflection] {task[:300]}",
                    skill_template=str(reflection.get("skill_template", "") or ""),
                    success=bool(result.get("success")),
                    metadata={"source": "reflection", "task_type": reflection.get("task_type", "")},
                )
            except Exception:
                pass
            return

        template = str(reflection.get("skill_template", "") or "").strip()
        if template and self._skill_store:
            try:
                self._skill_store.add(
                    task=f"[reflection] {task[:300]}",
                    code=template,
                    success=bool(result.get("success")),
                    metadata={"source": "reflection", "task_type": reflection.get("task_type", "")},
                )
            except Exception:
                pass
        if self._vector_store:
            try:
                semantic_text = "\n".join(
                    [
                        f"task: {task[:500]}",
                        f"task_type: {reflection.get('task_type', '')}",
                        f"failure_pattern: {reflection.get('failure_pattern', '')}",
                        f"improved_prompt: {reflection.get('improved_prompt', '')[:1000]}",
                    ]
                )
                self._vector_store.add(semantic_text, metadata={"source": "reflection"})
            except Exception:
                pass
