# gtos/executor/skill_store.py
"""成功流程/技能存储。最小实现：JSON 文件。"""

import json
import time
from pathlib import Path
from typing import Any

from gtos.core.interfaces.skill import SkillStoreProtocol
from gtos.skill_engine import SkillDecay, SkillEvaluator, SkillOptimizer, SkillVersioning


def _default_skills_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "skills.json"


class SkillStore(SkillStoreProtocol):
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _default_skills_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._evaluator = SkillEvaluator()
        self._versioning = SkillVersioning()
        self._decay = SkillDecay()
        self._optimizer = SkillOptimizer()
        self._skills: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            # Corrupted runtime state should not break the whole executor.
            try:
                broken = self._path.with_suffix(self._path.suffix + f".broken-{int(time.time())}")
                self._path.replace(broken)
            except Exception:
                pass
            return []
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        now = time.time()
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append(self._ensure_schema(item, now_ts=now))
        return out

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._skills, f, ensure_ascii=False, indent=2)

    def add(self, task: str, code: str, success: bool = True, metadata: dict[str, Any] | None = None) -> None:
        now = time.time()
        task_key = self._versioning.build_task_key(task)
        skill_id = self._versioning.build_skill_id(task, code)
        version = self._versioning.next_version(task_key, self._skills)
        fix_rounds = int((metadata or {}).get("fix_rounds", 0) or 0)
        error = str((metadata or {}).get("error", "") or "")
        record = {
            "task": task,
            "task_key": task_key,
            "code": code,
            "success": bool(success),
            "error": error[:600],
            "skill_id": skill_id,
            "version": version,
            "created_at": now,
            "last_used_at": now,
            "usage_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "first_pass_success_count": 0,
            "total_fix_rounds": 0,
            "avg_fix_rounds": 0.0,
            "score": 0.5,
            "expired": False,
            "status": "active",
            "metadata": metadata or {},
        }
        record = self._evaluator.update_run_stats(record, success=bool(success), fix_rounds=fix_rounds, now_ts=now)
        record = self._decay.apply(record, now_ts=now)
        self._skills.append(record)
        self._save()

    def get_recent(self, n: int = 5) -> list[dict[str, Any]]:
        if not self._skills:
            return []
        items = [s for s in self._skills if not s.get("expired", False)]
        if not items:
            items = list(self._skills)
        items.sort(key=lambda x: (float(x.get("last_used_at", 0.0) or 0.0), float(x.get("score", 0.0) or 0.0)))
        return items[-n:]

    def search_by_task(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        hits = [s for s in self._skills if (not s.get("expired", False)) and q in s.get("task", "").lower()]
        hits.sort(key=lambda x: (-float(x.get("score", 0.0) or 0.0), -int(x.get("version", 1) or 1)))
        return hits

    def list_all(self) -> list[dict[str, Any]]:
        self._refresh_lifecycle()
        return list(self._skills)

    def get_latest_by_task(self, task: str) -> dict[str, Any] | None:
        task_key = self._versioning.build_task_key(task)
        candidates = [s for s in self._skills if str(s.get("task_key", "")) == task_key]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (int(x.get("version", 1) or 1), float(x.get("last_used_at", 0.0) or 0.0)), reverse=True)
        return dict(candidates[0])

    def auto_optimize_from_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        task = str(result.get("task") or result.get("_task") or "").strip()
        if not task:
            return None
        skill = self.get_latest_by_task(task)
        if not skill:
            return None
        if not self._optimizer.should_optimize(skill):
            return None
        draft = self._optimizer.build_draft(skill, result)
        self._optimizer.save_draft(draft)
        return draft

    def get_proposed_draft_for_task(self, task: str) -> dict[str, Any] | None:
        task_key = self._versioning.build_task_key(task)
        return self._optimizer.find_latest_draft(task_key=task_key, statuses={"proposed"})

    def record_draft_outcome(self, task: str, result: dict[str, Any], draft_id: str | None = None) -> dict[str, Any] | None:
        task = str(task or "").strip()
        if not task:
            return None
        latest_skill = self.get_latest_by_task(task)
        if not latest_skill:
            return None
        if not draft_id:
            draft = self._optimizer.find_latest_draft(
                task_key=self._versioning.build_task_key(task),
                statuses={"proposed"},
            )
            if not draft:
                return None
            draft_id = str(draft.get("draft_id", ""))
        draft = self._optimizer.update_draft_status(draft_id, status="proposed")
        if not draft:
            return None

        success = bool(result.get("success"))
        if success:
            before_score = float(draft.get("score_at_proposal", 0.0) or 0.0)
            accepted_score = float(latest_skill.get("score", 0.0) or 0.0)
            uplift = round(accepted_score - before_score, 4)
            updated = self._optimizer.update_draft_status(
                draft_id,
                status="accepted",
                extra={
                    "acceptance": {
                        "accepted_at": time.time(),
                        "accepted_skill_id": latest_skill.get("skill_id", ""),
                        "accepted_version": int(latest_skill.get("version", 1) or 1),
                        "before_score": before_score,
                        "accepted_score": accepted_score,
                        "score_uplift": uplift,
                    }
                },
            )
            self._annotate_skill(latest_skill.get("skill_id", ""), {"accepted_from_draft_id": draft_id, "score_uplift": uplift})
            return updated

        updated = self._optimizer.update_draft_status(
            draft_id,
            status="rejected",
            extra={
                "rejection": {
                    "rejected_at": time.time(),
                    "reason": str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "execution_failed")[:240],
                }
            },
        )
        return updated

    def _refresh_lifecycle(self) -> None:
        now = time.time()
        changed = False
        for i, skill in enumerate(self._skills):
            normalized = self._ensure_schema(skill, now_ts=now)
            normalized["score"] = self._evaluator.score(normalized, now_ts=now)
            normalized = self._decay.apply(normalized, now_ts=now)
            if normalized != skill:
                self._skills[i] = normalized
                changed = True
        if changed:
            self._save()

    def _ensure_schema(self, item: dict[str, Any], now_ts: float | None = None) -> dict[str, Any]:
        now = now_ts or time.time()
        task = str(item.get("task", "") or "")
        code = str(item.get("code", "") or "")
        task_key = str(item.get("task_key") or self._versioning.build_task_key(task))
        skill_id = str(item.get("skill_id") or self._versioning.build_skill_id(task, code))
        out = dict(item)
        out.setdefault("task", task)
        out.setdefault("code", code)
        out.setdefault("success", bool(item.get("success", True)))
        out.setdefault("error", str(item.get("error", "") or ""))
        out.setdefault("task_key", task_key)
        out.setdefault("skill_id", skill_id)
        out.setdefault("version", int(item.get("version", 1) or 1))
        out.setdefault("created_at", float(item.get("created_at", now) or now))
        out.setdefault("last_used_at", float(item.get("last_used_at", out["created_at"]) or out["created_at"]))
        out.setdefault("usage_count", int(item.get("usage_count", 0) or 0))
        out.setdefault("success_count", int(item.get("success_count", 1 if out.get("success") else 0) or 0))
        out.setdefault("fail_count", int(item.get("fail_count", 0 if out.get("success") else 1) or 0))
        out.setdefault("first_pass_success_count", int(item.get("first_pass_success_count", 1 if out.get("success") else 0) or 0))
        out.setdefault("total_fix_rounds", int(item.get("total_fix_rounds", 0) or 0))
        out.setdefault("avg_fix_rounds", float(item.get("avg_fix_rounds", 0.0) or 0.0))
        out.setdefault("score", float(item.get("score", 0.5) or 0.5))
        out.setdefault("expired", bool(item.get("expired", False)))
        out.setdefault("status", "expired" if out.get("expired") else "active")
        out.setdefault("metadata", item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {})
        return out

    def _annotate_skill(self, skill_id: str, fields: dict[str, Any]) -> None:
        if not skill_id:
            return
        changed = False
        for i, s in enumerate(self._skills):
            if str(s.get("skill_id", "")) == str(skill_id):
                new = dict(s)
                meta = dict(new.get("metadata", {}) if isinstance(new.get("metadata", {}), dict) else {})
                meta.update(fields or {})
                new["metadata"] = meta
                self._skills[i] = new
                changed = True
                break
        if changed:
            self._save()
