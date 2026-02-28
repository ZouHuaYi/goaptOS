import shutil
import tempfile
from pathlib import Path

from gtos.core.session import SessionManager, SessionStorage


def test_session_manager_builds_context_and_compresses() -> None:
    d = Path(tempfile.mkdtemp(prefix="session-mem-", dir="."))
    try:
        store = SessionStorage(d / "sessions.json")
        manager = SessionManager(store, keep_recent_messages=4, compress_threshold=5, max_context_chars=2000, max_summary_chars=400)
        sid = manager.ensure_session("abc")
        for i in range(7):
            manager.append_message(sid, "user" if i % 2 == 0 else "assistant", f"msg-{i}")
        ctx = manager.build_context(sid)
        assert "[Recent Messages]" in ctx
        assert "msg-6" in ctx
        assert "msg-0" not in ctx
        assert "[Summary]" in ctx
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_session_manager_generates_session_id() -> None:
    d = Path(tempfile.mkdtemp(prefix="session-id-", dir="."))
    try:
        manager = SessionManager(SessionStorage(d / "sessions.json"))
        sid = manager.ensure_session(None)
        assert isinstance(sid, str)
        assert len(sid) >= 8
    finally:
        shutil.rmtree(d, ignore_errors=True)

