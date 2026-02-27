# gtos/memory/sqlite_store.py
"""SQLite 持久化：执行历史、任务元数据。"""

import sqlite3
from pathlib import Path
from typing import Any


def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "gtos.db"


class SQLiteStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT,
                    success INTEGER,
                    created_at DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def log_execution(self, task: str, success: bool) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT INTO executions (task, success) VALUES (?, ?)",
                (task[:1000], 1 if success else 0),
            )

    def get_recent(self, n: int = 10) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, task, success, created_at FROM executions ORDER BY id DESC LIMIT ?",
                (n,),
            )
            return [dict(row) for row in cur.fetchall()]
