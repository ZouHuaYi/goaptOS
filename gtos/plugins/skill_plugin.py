# gtos/plugins/skill_plugin.py
"""技能抽象与复用：pre 检索相似成功流程注入 prompt，post 将成功结果写入向量存储。"""

from gtos.executor.plugin_manager import Plugin
from gtos.executor.skill_store import SkillStore
from gtos.memory.vector_store import VectorStore


class SkillPlugin(Plugin):
    def __init__(
        self,
        skill_store: SkillStore | None = None,
        vector_store: VectorStore | None = None,
        recent_count: int = 3,
        retrieval_top_k: int = 5,
    ) -> None:
        self._store = skill_store or SkillStore()
        self._vector_store = vector_store
        self._recent_count = recent_count
        self._retrieval_top_k = retrieval_top_k

    def pre_execute(self, task_prompt: str) -> str:
        hints_parts = []
        if self._vector_store:
            hits = self._vector_store.search(task_prompt, top_k=self._retrieval_top_k)
            if hits:
                for h in hits:
                    hints_parts.append("- " + (h.get("text") or "")[:150])
        if not hints_parts:
            recent = self._store.get_recent(self._recent_count)
            for s in recent:
                hints_parts.append("- " + (s.get("task") or "")[:80])
        if not hints_parts:
            return task_prompt
        hints = "\n".join(hints_parts)
        return f"[Similar / recent successful tasks]\n{hints}\n\n[Current task]\n{task_prompt}"

    def post_execute(self, result: dict) -> dict:
        if result.get("success") and self._vector_store:
            task = result.get("task") or result.get("_task") or ""
            code = result.get("code") or ""
            if task or code:
                text = (task + "\n" + code[:500]).strip()
                self._vector_store.add(text, metadata={"task": task[:500], "code_len": len(code)})
        return result

    def on_error(self, error_info: str) -> str:
        return error_info
