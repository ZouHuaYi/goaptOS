"""Persistent storage for chat sessions."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any


class SessionStorage:
    def __init__(self, file_path: str | Path) -> None:
        self._file = Path(file_path)
        self._lock = RLock()

    @property
    def path(self) -> str:
        return str(self._file)

    def load_all(self) -> dict[str, Any]:
        with self._lock:
            if not self._file.exists():
                return {}
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                return {}
            return {}

    def save_all(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(self._file.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._file)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        all_data = self.load_all()
        raw = all_data.get(session_id)
        return raw if isinstance(raw, dict) else None

    def save_session(self, session_id: str, session_data: dict[str, Any]) -> None:
        all_data = self.load_all()
        all_data[session_id] = session_data
        self.save_all(all_data)

