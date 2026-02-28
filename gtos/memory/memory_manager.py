"""Unified long-term memory manager (episodic / semantic / skill)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class MemoryManager:
    def __init__(
        self,
        *,
        sqlite_db: str | Path,
        vector_store: Any | None = None,
        skill_store: Any | None = None,
    ) -> None:
        self._db = Path(sqlite_db)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._vector_store = vector_store
        self._skill_store = skill_store
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT,
                    success INTEGER,
                    fix_rounds INTEGER,
                    error TEXT,
                    payload_json TEXT,
                    created_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary TEXT,
                    tags_json TEXT,
                    source TEXT,
                    created_at REAL
                )
                """
            )

    def write_episode(self, task: str, result: dict[str, Any], payload: dict[str, Any] | None = None) -> int:
        success = 1 if bool(result.get("success")) else 0
        fix_rounds = int(result.get("fix_rounds", 0) or 0)
        error = str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "")[:800]
        extra = payload if isinstance(payload, dict) else {}
        merged = {"result": self._compact_result(result), "extra": extra}
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            cur = conn.execute(
                """
                INSERT INTO episodic_memory (task, success, fix_rounds, error, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task[:1200], success, fix_rounds, error, json.dumps(merged, ensure_ascii=False), now),
            )
            row_id = int(cur.lastrowid or 0)
        self._auto_abstract_episodic_to_semantic(task=task, result=result)
        return row_id

    def write_semantic(self, summary: str, tags: dict[str, Any] | None = None, source: str = "reflection") -> int:
        text = (summary or "").strip()
        if not text:
            return 0
        tags_json = json.dumps(tags or {}, ensure_ascii=False)
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            cur = conn.execute(
                """
                INSERT INTO semantic_memory (summary, tags_json, source, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (text[:2000], tags_json, source[:80], now),
            )
            row_id = int(cur.lastrowid or 0)
        if self._vector_store:
            try:
                self._vector_store.add(text[:2000], metadata={"source": source[:80], **(tags or {})})
            except Exception:
                pass
        return row_id

    def write_skill(self, task: str, skill_template: str, success: bool = True, metadata: dict[str, Any] | None = None) -> None:
        if not self._skill_store:
            return
        code = (skill_template or "").strip()
        if not code:
            return
        try:
            self._skill_store.add(task=task, code=code, success=success, metadata=metadata or {"source": "memory_manager"})
        except Exception:
            return

    def query(self, query_text: str, top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        q = (query_text or "").strip()
        if not q:
            return {"episodic": [], "semantic": []}
        out: dict[str, list[dict[str, Any]]] = {"episodic": [], "semantic": []}

        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            pat = f"%{q[:120]}%"
            episodic_rows = conn.execute(
                """
                SELECT id, task, success, fix_rounds, error, created_at
                FROM episodic_memory
                WHERE task LIKE ? OR error LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (pat, pat, max(1, int(top_k))),
            ).fetchall()
            semantic_rows = conn.execute(
                """
                SELECT id, summary, tags_json, source, created_at
                FROM semantic_memory
                WHERE summary LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (pat, max(1, int(top_k))),
            ).fetchall()
        out["episodic"] = [dict(r) for r in episodic_rows]
        out["semantic"] = [self._row_semantic_dict(r) for r in semantic_rows]

        if self._vector_store:
            try:
                hits = self._vector_store.search(q, top_k=max(1, int(top_k)))
                for h in hits or []:
                    out["semantic"].append(
                        {
                            "id": 0,
                            "summary": str(h.get("text", "") or "")[:2000],
                            "tags": h.get("metadata", {}) if isinstance(h.get("metadata", {}), dict) else {},
                            "source": "vector",
                            "created_at": 0.0,
                        }
                    )
            except Exception:
                pass
        return out

    def _auto_abstract_episodic_to_semantic(self, *, task: str, result: dict[str, Any]) -> None:
        if bool(result.get("success")):
            return
        error = str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "")
        if "No module named" in error:
            episodes = self._recent_episodes(limit=12)
            dep_failures = [e for e in episodes if "No module named" in str(e.get("error", ""))]
            if len(dep_failures) >= 2:
                summary = (
                    "Repeated dependency import errors detected. "
                    "Use a dependency bootstrap template: capture ImportError, print install hint, "
                    "and optionally fallback to stdlib implementation."
                )
                self.write_semantic(
                    summary=summary,
                    tags={"pattern": "missing_dependency", "count": len(dep_failures), "task_hint": task[:180]},
                    source="episodic_auto_abstract",
                )

    def _recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, task, success, fix_rounds, error, created_at
                FROM episodic_memory
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(r) for r in rows]

    def _compact_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": bool(result.get("success")),
            "fix_rounds": int(result.get("fix_rounds", 0) or 0),
            "error": str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "")[:400],
            "stdout": str(result.get("stdout", "") or "")[:400],
            "stderr": str(result.get("stderr", "") or "")[:400],
        }

    def _row_semantic_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        tags_obj: dict[str, Any] = {}
        try:
            raw = row["tags_json"] or "{}"
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                tags_obj = parsed
        except Exception:
            tags_obj = {}
        return {
            "id": row["id"],
            "summary": row["summary"],
            "tags": tags_obj,
            "source": row["source"],
            "created_at": row["created_at"],
        }

