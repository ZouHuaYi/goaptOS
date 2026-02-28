"""Automatic draft generator for low-performing skills."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class SkillOptimizer:
    def __init__(
        self,
        drafts_path: str | Path = "data/skill_drafts.json",
        low_score_threshold: float = 0.35,
        min_fail_count: int = 1,
    ) -> None:
        self._drafts_path = Path(drafts_path)
        self._drafts_path.parent.mkdir(parents=True, exist_ok=True)
        self._low_score_threshold = float(low_score_threshold)
        self._min_fail_count = int(min_fail_count)

    def should_optimize(self, skill: dict[str, Any]) -> bool:
        if not skill:
            return False
        score = float(skill.get("score", 0.5) or 0.5)
        fail_count = int(skill.get("fail_count", 0) or 0)
        success_count = int(skill.get("success_count", 0) or 0)
        return (score <= self._low_score_threshold and fail_count >= self._min_fail_count) or (fail_count > success_count + 1)

    def build_draft(self, skill: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        task = str(skill.get("task", "") or result.get("task", "") or "")
        code = str(skill.get("code", "") or result.get("code", "") or "")
        error = str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "")
        now = time.time()
        draft = {
            "draft_id": f"draft-{int(now * 1000)}",
            "created_at": now,
            "status": "proposed",
            "task_key": skill.get("task_key", ""),
            "from_skill_id": skill.get("skill_id", ""),
            "from_version": int(skill.get("version", 1) or 1),
            "target_version": int(skill.get("version", 1) or 1) + 1,
            "score_at_proposal": float(skill.get("score", 0.0) or 0.0),
            "reason": self._build_reason(skill, error),
            "proposal": {
                "prompt_template": self._build_prompt_template(task, error),
                "patch_hints": self._build_patch_hints(error),
                "base_code_preview": code[:600],
            },
        }
        return draft

    def save_draft(self, draft: dict[str, Any]) -> None:
        data = self._load_drafts()
        existing = {(d.get("task_key"), int(d.get("target_version", 0) or 0)) for d in data if isinstance(d, dict)}
        key = (draft.get("task_key"), int(draft.get("target_version", 0) or 0))
        if key in existing:
            return
        data.append(draft)
        self._save_drafts(data)

    def summarize_drafts(self, limit: int = 20) -> dict[str, Any]:
        items = self._load_drafts()
        recent = [d for d in items if isinstance(d, dict)][-max(1, limit) :]
        accepted_items = [d for d in items if str((d or {}).get("status", "")) == "accepted"]
        uplifts = [float((d or {}).get("acceptance", {}).get("score_uplift", 0.0) or 0.0) for d in accepted_items]
        return {
            "total": len(items),
            "proposed": sum(1 for d in items if str((d or {}).get("status", "")) == "proposed"),
            "accepted": sum(1 for d in items if str((d or {}).get("status", "")) == "accepted"),
            "rejected": sum(1 for d in items if str((d or {}).get("status", "")) == "rejected"),
            "acceptance_rate": round((len(accepted_items) / len(items)), 4) if items else 0.0,
            "avg_score_uplift": round(sum(uplifts) / len(uplifts), 4) if uplifts else 0.0,
            "recent": recent,
        }

    def find_latest_draft(self, task_key: str, statuses: set[str] | None = None) -> dict[str, Any] | None:
        items = self._load_drafts()
        allowed = statuses or {"proposed", "accepted", "rejected"}
        candidates = [d for d in items if str((d or {}).get("task_key", "")) == str(task_key) and str((d or {}).get("status", "")) in allowed]
        if not candidates:
            return None
        candidates.sort(key=lambda x: float((x or {}).get("created_at", 0.0) or 0.0), reverse=True)
        return candidates[0]

    def update_draft_status(self, draft_id: str, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
        items = self._load_drafts()
        target = None
        for i, d in enumerate(items):
            if str((d or {}).get("draft_id", "")) == str(draft_id):
                out = dict(d)
                out["status"] = status
                out["updated_at"] = time.time()
                if extra:
                    out.update(extra)
                items[i] = out
                target = out
                break
        if target:
            self._save_drafts(items)
        return target

    def _build_reason(self, skill: dict[str, Any], error: str) -> str:
        score = float(skill.get("score", 0.0) or 0.0)
        fail_count = int(skill.get("fail_count", 0) or 0)
        if error:
            return f"low-performing skill (score={score:.2f}, fails={fail_count}) with recurring error: {error[:120]}"
        return f"low-performing skill (score={score:.2f}, fails={fail_count})"

    def _build_prompt_template(self, task: str, error: str) -> str:
        lines = [
            "You are improving an existing skill implementation.",
            "Task:",
            task[:400] or "<empty task>",
            "",
            "Constraints:",
            "- Keep solution concise and deterministic.",
            "- Prefer standard library and explicit error handling.",
            "- Include minimal validation and clear output.",
        ]
        if error:
            lines.extend(["", "Prior failure signal:", error[:240]])
        return "\n".join(lines)

    def _build_patch_hints(self, error: str) -> list[str]:
        e = error.lower()
        hints = ["Add explicit input checks and fail-fast guards.", "Make side effects idempotent where possible."]
        if "syntax" in e:
            hints.append("Validate syntax and avoid multiline string/indent pitfalls.")
        if "module" in e or "import" in e:
            hints.append("Avoid non-standard dependencies and add import fallback.")
        if "timeout" in e:
            hints.append("Reduce complexity and avoid long-running loops.")
        if "typeerror" in e:
            hints.append("Normalize types before arithmetic or iteration.")
        return hints[:5]

    def _load_drafts(self) -> list[dict[str, Any]]:
        if not self._drafts_path.exists():
            return []
        try:
            with open(self._drafts_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
                if isinstance(obj, list):
                    return obj
        except Exception:
            return []
        return []

    def _save_drafts(self, drafts: list[dict[str, Any]]) -> None:
        tmp = self._drafts_path.with_suffix(self._drafts_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False, indent=2)
        tmp.replace(self._drafts_path)
