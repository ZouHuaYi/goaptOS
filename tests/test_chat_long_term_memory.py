import shutil
import tempfile
from pathlib import Path

from gtos.memory import MemoryManager
from gtos.web.chat_server import _persist_conversation_memory, _recall_conversation_memories


def test_chat_long_term_memory_persist_and_recall_same_session() -> None:
    d = Path(tempfile.mkdtemp(prefix="chat-ltm-", dir="."))
    try:
        mm = MemoryManager(sqlite_db=d / "m.db", vector_store=None, skill_store=None)
        sid = "s1"
        _persist_conversation_memory(mm, sid, "我们讨论过质数分片", "建议按区间并行")
        recalled = _recall_conversation_memories(mm, sid, "质数并行", top_k=3)
        assert recalled
        assert any("质数" in x or "并行" in x for x in recalled)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_chat_long_term_memory_filters_other_session() -> None:
    d = Path(tempfile.mkdtemp(prefix="chat-ltm-filter-", dir="."))
    try:
        mm = MemoryManager(sqlite_db=d / "m.db", vector_store=None, skill_store=None)
        _persist_conversation_memory(mm, "s-other", "只属于别的会话", "不应被召回")
        recalled = _recall_conversation_memories(mm, "s-self", "别的会话", top_k=3)
        assert recalled == []
    finally:
        shutil.rmtree(d, ignore_errors=True)

