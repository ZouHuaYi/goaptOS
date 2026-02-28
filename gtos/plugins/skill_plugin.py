# gtos/plugins/skill_plugin.py
"""技能抽象与复用：pre 检索相似成功流程注入 prompt，post 将成功结果写入向量存储。"""

import hashlib
import json
import threading
import time
from pathlib import Path

from gtos.core.events import EventName, ExecutionFailurePayload, ExecutionSuccessPayload, TaskPromptActionPayload
from gtos.core.interfaces.result import append_log, normalize_error
from gtos.executor.plugin_manager import Plugin
from gtos.executor.skill_store import SkillStore
from gtos.memory.skill_matcher import SkillMatcher
from gtos.memory.vector_store import VectorStore


class SkillPlugin(Plugin):
    def __init__(
        self,
        skill_store: SkillStore | None = None,
        vector_store: VectorStore | None = None,
        recent_count: int = 3,
        retrieval_top_k: int = 5,
        min_relevance: float = 0.22,
        max_context_chars: int = 900,
        ab_test: dict | None = None,
    ) -> None:
        self._store = skill_store or SkillStore()
        self._vector_store = vector_store
        self._recent_count = recent_count
        self._retrieval_top_k = retrieval_top_k
        self._min_relevance = min_relevance
        self._matcher = SkillMatcher(
            skill_store=self._store,
            vector_store=self._vector_store,
            min_relevance=min_relevance,
            max_context_chars=max_context_chars,
        )
        self._local = threading.local()
        self._ab_lock = threading.Lock()
        cfg = ab_test or {}
        self._ab_mode = str(cfg.get("mode", "auto")).lower()  # off/control/treatment/auto
        self._ab_ratio = float(cfg.get("treatment_ratio", 0.5))
        self._ab_salt = str(cfg.get("salt", "skill-ab-v1"))
        self._ab_metrics_path = Path(cfg.get("metrics_file", "data/skill_ab_metrics.json"))

    def _pre_execute(self, task_prompt: str) -> str:
        bucket = self._pick_bucket(task_prompt)
        self._local.ab_bucket = bucket
        self._local.applied_draft_id = ""

        # If there is a proposed optimization draft for this task, attach its prompt template.
        draft = self._store.get_proposed_draft_for_task(task_prompt) if hasattr(self._store, "get_proposed_draft_for_task") else None
        if draft:
            draft_prompt = str(((draft.get("proposal", {}) or {}).get("prompt_template", "") or "")).strip()
            if draft_prompt:
                self._local.applied_draft_id = str(draft.get("draft_id", ""))
                task_prompt = "\n".join(
                    [
                        "[Skill optimization draft]",
                        draft_prompt,
                        "",
                        "[Current task]",
                        task_prompt,
                    ]
                )

        if bucket in {"control", "off"}:
            return task_prompt

        hits = self._matcher.retrieve(task_prompt, top_k=self._retrieval_top_k)
        if not hits:
            recent = self._store.get_recent(self._recent_count)
            hits = [
                {
                    "task": s.get("task", ""),
                    "text": s.get("task", ""),
                    "code": s.get("code", ""),
                    "success": bool(s.get("success", True)),
                    "source": "recent",
                }
                for s in recent
            ]
        return self._matcher.build_context(task_prompt, hits) if hits else task_prompt

    def _post_execute(self, result: dict) -> dict:
        out = dict(result)
        bucket = getattr(self._local, "ab_bucket", "unknown")
        self._update_ab_metrics(bucket=bucket, result=out)

        if out.get("success") and self._vector_store:
            task = out.get("task") or out.get("_task") or ""
            code = out.get("code") or ""
            if task or code:
                text = (task + "\n" + code[:500]).strip()
                self._vector_store.add(text, metadata={"task": task[:500], "code_len": len(code)})
        out = append_log(
            out,
            level="info",
            event="plugin.skill.post_execute",
            message="skill plugin updated retrieval/ab-test artifacts",
            ab_bucket=bucket,
        )
        applied_draft_id = str(getattr(self._local, "applied_draft_id", "") or "")
        if applied_draft_id and hasattr(self._store, "record_draft_outcome"):
            outcome = self._store.record_draft_outcome(str(out.get("task", "") or ""), out, draft_id=applied_draft_id)
            if outcome:
                out = append_log(
                    out,
                    level="info",
                    event="plugin.skill.draft_outcome",
                    message="draft outcome recorded",
                    draft_id=applied_draft_id,
                    status=str(outcome.get("status", "")),
                )
                out.setdefault("_skill_optimization", {})["applied_draft"] = {
                    "draft_id": applied_draft_id,
                    "status": str(outcome.get("status", "")),
                }
        try:
            draft = self._store.auto_optimize_from_result(out) if hasattr(self._store, "auto_optimize_from_result") else None
            if draft:
                out = append_log(
                    out,
                    level="warn",
                    event="plugin.skill.auto_optimize",
                    message="auto optimization draft proposed for low-performing skill",
                    draft_id=str(draft.get("draft_id", "")),
                    from_skill_id=str(draft.get("from_skill_id", "")),
                    target_version=int(draft.get("target_version", 0) or 0),
                )
                out.setdefault("_skill_optimization", {})["draft"] = draft
        except Exception as e:
            out = append_log(out, level="error", event="plugin.skill.auto_optimize_failed", message=str(e)[:240])
        return out

    def on_event(self, event) -> None:
        if event.name == EventName.ON_ACTION and isinstance(event.payload, TaskPromptActionPayload):
            event.payload.task_prompt = self._pre_execute(str(event.payload.task_prompt or ""))
            return
        if event.name == EventName.ON_EXECUTION_SUCCESS and isinstance(event.payload, ExecutionSuccessPayload):
            result = event.payload.result
            if isinstance(result, dict):
                event.payload.result = self._post_execute(result)
            return
        if event.name == EventName.ON_EXECUTION_FAILURE and isinstance(event.payload, ExecutionFailurePayload):
            event.payload.error_info = normalize_error(event.payload.error_info, default_code="skill_error", retriable=False)

    def _pick_bucket(self, task_prompt: str) -> str:
        mode = self._ab_mode
        if mode in {"off", "control", "treatment"}:
            return mode
        raw = f"{self._ab_salt}::{task_prompt}".encode("utf-8")
        h = hashlib.sha256(raw).hexdigest()
        val = int(h[:8], 16) / 0xFFFFFFFF
        return "treatment" if val < self._ab_ratio else "control"

    def _update_ab_metrics(self, bucket: str, result: dict) -> None:
        if bucket not in {"control", "treatment", "off"}:
            return
        with self._ab_lock:
            data = self._load_ab_metrics()
            stat = data.setdefault(bucket, {"runs": 0, "success": 0, "first_pass_success": 0})
            stat["runs"] += 1
            if result.get("success"):
                stat["success"] += 1
            if result.get("success") and int(result.get("fix_rounds", 0) or 0) == 0:
                stat["first_pass_success"] += 1
            stat["success_rate"] = round(stat["success"] / stat["runs"], 4) if stat["runs"] else 0.0
            stat["first_pass_rate"] = round(stat["first_pass_success"] / stat["runs"], 4) if stat["runs"] else 0.0
            data["updated_ts"] = time.time()
            self._save_ab_metrics(data)

    def _load_ab_metrics(self) -> dict:
        if not self._ab_metrics_path.exists():
            return {}
        try:
            with open(self._ab_metrics_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
                return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _save_ab_metrics(self, payload: dict) -> None:
        self._ab_metrics_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._ab_metrics_path.with_suffix(self._ab_metrics_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self._ab_metrics_path)
