"""Session-level chat memory manager."""

from __future__ import annotations

import time
import uuid
from threading import RLock
from typing import Any

from gtos.core.session.storage import SessionStorage


class SessionManager:
    def __init__(
        self,
        storage: SessionStorage,
        *,
        keep_recent_messages: int = 10,
        compress_threshold: int = 14,
        max_context_chars: int = 3000,
        max_summary_chars: int = 1200,
    ) -> None:
        self._storage = storage
        self._keep_recent = max(4, int(keep_recent_messages))
        self._compress_threshold = max(self._keep_recent + 1, int(compress_threshold))
        self._max_context_chars = max(800, int(max_context_chars))
        self._max_summary_chars = max(300, int(max_summary_chars))
        self._lock = RLock()

    def ensure_session(self, session_id: str | None = None) -> str:
        sid = (session_id or "").strip() or str(uuid.uuid4())
        with self._lock:
            sess = self._storage.load_session(sid)
            if not isinstance(sess, dict):
                now = time.time()
                sess = {
                    "session_id": sid,
                    "created_at": now,
                    "updated_at": now,
                    "summary": "",
                    "messages": [],
                }
                self._storage.save_session(sid, sess)
            return sid

    def append_message(self, session_id: str, role: str, content: str) -> None:
        role_norm = "assistant" if str(role).strip().lower() == "assistant" else "user"
        text = str(content or "").strip()
        if not text:
            return
        text = text[:4000]
        with self._lock:
            sid = self.ensure_session(session_id)
            sess = self._storage.load_session(sid) or {}
            messages = sess.get("messages", [])
            if not isinstance(messages, list):
                messages = []
            messages.append({"role": role_norm, "content": text, "ts": time.time()})
            sess["messages"] = messages
            sess["updated_at"] = time.time()
            self._compress_if_needed(sess)
            self._storage.save_session(sid, sess)

    def build_context(self, session_id: str) -> str:
        with self._lock:
            sid = self.ensure_session(session_id)
            sess = self._storage.load_session(sid) or {}
            summary = str(sess.get("summary", "") or "").strip()
            messages = sess.get("messages", [])
            if not isinstance(messages, list):
                messages = []

            lines: list[str] = []
            if summary:
                lines.append("[Summary]")
                lines.append(summary)
            if messages:
                lines.append("[Recent Messages]")
                for m in messages[-self._keep_recent :]:
                    role = "用户" if str(m.get("role", "")).lower() == "user" else "助手"
                    content = str(m.get("content", "") or "").strip()
                    if content:
                        lines.append(f"{role}: {content}")
            text = "\n".join(lines).strip()
            if len(text) <= self._max_context_chars:
                return text
            return text[-self._max_context_chars :]

    def _compress_if_needed(self, sess: dict[str, Any]) -> None:
        messages = sess.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        if len(messages) <= self._compress_threshold:
            sess["messages"] = messages
            return
        old = messages[: -self._keep_recent]
        recent = messages[-self._keep_recent :]
        summary = str(sess.get("summary", "") or "").strip()
        new_bits: list[str] = []
        for m in old[-12:]:
            role = "U" if str(m.get("role", "")).lower() == "user" else "A"
            content = str(m.get("content", "") or "").replace("\n", " ").strip()
            if content:
                new_bits.append(f"{role}:{content[:100]}")
        if new_bits:
            merged = (summary + " | " + " | ".join(new_bits)).strip(" |")
            sess["summary"] = merged[-self._max_summary_chars :]
        sess["messages"] = recent

