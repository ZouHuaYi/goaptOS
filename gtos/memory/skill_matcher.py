"""Skill matching: hybrid retrieval + rerank + prompt context building."""

from typing import Any


class SkillMatcher:
    def __init__(self, skill_store: Any, vector_store: Any = None, min_relevance: float = 0.22, max_context_chars: int = 900) -> None:
        self._store = skill_store
        self._vector_store = vector_store
        self._min_relevance = float(min_relevance)
        self._max_context_chars = int(max_context_chars)
        self._generic_tokens = {
            "python", "code", "script", "task", "print", "output", "current", "similar", "recent",
            "successful", "tasks", "please", "help", "write", "生成", "代码", "任务", "输出", "当前", "类似",
        }

    def retrieve(self, task_prompt: str, top_k: int = 5) -> list[dict[str, Any]]:
        query = (task_prompt or "").strip()
        if not query:
            return []
        pool: list[dict[str, Any]] = []
        pool.extend(self._from_vector(query, top_k=max(3, top_k)))
        pool.extend(self._from_store(query, top_k=max(6, top_k * 2)))
        reranked = self.rerank(query, pool)
        reranked = [x for x in reranked if float(x.get("score", 0.0)) >= self._min_relevance]
        return reranked[: max(1, top_k)]

    def rerank(self, task_prompt: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_words = self._words(task_prompt)
        query_specific = self._specific_words(task_prompt)
        best: dict[str, dict[str, Any]] = {}
        for c in candidates:
            text = (c.get("text") or "").strip()
            if not text:
                continue
            task = c.get("task") or ""
            source = c.get("source") or "unknown"
            success = bool(c.get("success", True))
            lifecycle_score = float(c.get("skill_score", 0.5) or 0.5)
            candidate_words = self._words(text)
            overlap = self._overlap(query_words, candidate_words)
            specific_overlap = self._overlap(query_specific, self._specific_words(text))
            quality = self._quality_score(task=task or text, code=(c.get("code") or text), success=success)
            source_bias = 0.06 if source == "vector" else 0.03
            score = overlap * 0.4 + specific_overlap * 0.3 + quality * 0.14 + lifecycle_score * 0.1 + source_bias
            if specific_overlap <= 0 and overlap < 0.25:
                score *= 0.35
            key = self._dedupe_key(task or text)
            prev = best.get(key)
            if prev is None or score > prev["score"]:
                best[key] = {**c, "score": round(score, 4)}
        out = list(best.values())
        out.sort(key=lambda x: -float(x.get("score", 0.0)))
        return out

    def build_context(self, task_prompt: str, hits: list[dict[str, Any]]) -> str:
        if not hits:
            return task_prompt
        good = [h for h in hits if h.get("success", True)]
        bad = [h for h in hits if not h.get("success", True)]

        lines = ["[Similar successful tasks]"]
        for h in good[:4]:
            task = (h.get("task") or h.get("text") or "").strip().replace("\n", " ")
            lines.append(f"- {task[:180]}")

        if bad:
            lines.append("")
            lines.append("[Do-not-repeat patterns]")
            for h in bad[:2]:
                t = (h.get("task") or h.get("text") or "").strip().replace("\n", " ")
                e = (h.get("error") or "").strip().replace("\n", " ")
                snippet = t[:120]
                if e:
                    snippet += f" | error: {e[:80]}"
                lines.append(f"- {snippet}")

        lines.append("")
        lines.append("[Current task]")
        lines.append(task_prompt)
        out = "\n".join(lines)
        if len(out) > self._max_context_chars:
            return task_prompt
        return out

    def _from_vector(self, query: str, top_k: int) -> list[dict[str, Any]]:
        if self._vector_store is None:
            return []
        try:
            hits = self._vector_store.search(query, top_k=top_k)
        except Exception:
            return []
        out = []
        for h in hits or []:
            text = (h.get("text") or "").strip()
            meta = h.get("metadata") or {}
            if not text:
                continue
            out.append(
                {
                    "task": meta.get("task") or "",
                    "code": "",
                    "text": text,
                    "success": True,
                    "error": "",
                    "source": "vector",
                }
            )
        return out

    def _from_store(self, query: str, top_k: int) -> list[dict[str, Any]]:
        items = self._store.list_all() if hasattr(self._store, "list_all") else []
        if not items:
            return []
        scored = []
        q = self._words(query)
        for s in items:
            task = (s.get("task") or "").strip()
            code = (s.get("code") or "").strip()
            if bool(s.get("expired", False)):
                continue
            if not task and not code:
                continue
            text = (task + "\n" + code[:400]).strip()
            overlap = self._overlap(q, self._words(text))
            if overlap <= 0:
                continue
            scored.append(
                {
                    "task": task,
                    "code": code,
                    "text": text,
                    "success": bool(s.get("success", True)),
                    "error": (s.get("error") or "")[:400],
                    "source": "store",
                    "score": overlap,
                    "skill_score": float(s.get("score", 0.5) or 0.5),
                }
            )
        scored.sort(key=lambda x: -float(x.get("score", 0.0)))
        return scored[: max(1, top_k)]

    def _quality_score(self, task: str, code: str, success: bool) -> float:
        base = 1.0 if success else 0.2
        task_len = len(task or "")
        code_len = len(code or "")
        if task_len > 500:
            base -= 0.2
        if code_len < 10:
            base -= 0.2
        if self._dup_ratio(task) > 0.5:
            base -= 0.2
        if self._dup_ratio(code) > 0.5:
            base -= 0.2
        return max(0.0, min(1.0, base))

    def _words(self, text: str) -> set[str]:
        out = []
        buff = []
        for ch in (text or "").lower():
            if ch.isalnum() or ch in {"_", "-"}:
                buff.append(ch)
            else:
                if buff:
                    out.append("".join(buff))
                    buff = []
        if buff:
            out.append("".join(buff))
        return set(w for w in out if len(w) >= 2 and w not in self._generic_tokens)

    def _specific_words(self, text: str) -> set[str]:
        ws = self._words(text)
        specific = {w for w in ws if any(ch.isdigit() for ch in w) or len(w) >= 4}
        return specific if specific else ws

    def _overlap(self, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        return inter / max(1, len(a))

    def _dup_ratio(self, text: str) -> float:
        words = [w for w in (text or "").split() if w]
        if not words:
            return 0.0
        uniq = len(set(words))
        return 1.0 - (uniq / len(words))

    def _dedupe_key(self, text: str) -> str:
        t = " ".join((text or "").lower().split())
        return t[:140]
