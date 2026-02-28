"""Simple local chat API for GTOS web UI."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse

from gtos.config import get_data_dir, load_config
from gtos.core.capability import MCPCapabilityAdapter, build_mcp_server_configs
from gtos.core.session import SessionManager, SessionStorage
from gtos.main import execute_once
from gtos.memory import MemoryManager, get_vector_store
from gtos.observability import EventTraceReplayer
from gtos.plugins import PluginMarketplace


def _extract_reply(result: dict, detailed: bool = False) -> str:
    def _one_node_text(node: dict) -> str:
        node_id = str(node.get("id", "") or "").strip()
        prefix = f"[{node_id}] " if node_id else ""
        out = str(node.get("stdout") or "").strip()
        if out:
            return prefix + out
        err = str(node.get("error") or (node.get("_error", {}) or {}).get("message") or "").strip()
        if err:
            return prefix + f"执行失败：{err}"
        if bool(node.get("success")):
            code = str(node.get("code") or "").strip()
            if code:
                first = code.splitlines()[:2]
                return prefix + "执行成功（无 stdout）。代码片段：" + " | ".join(first)
            return prefix + "执行成功（无 stdout）。"
        return prefix + "执行完成（无可展示输出）。"

    if result.get("rejected"):
        return f"任务被拒绝：{result.get('reason')}（风险：{result.get('risk')}）"
    if result.get("results"):
        rows = result.get("results", [])
        lines = [_one_node_text(r) for r in rows if isinstance(r, dict)]
        summary = result.get("summary", {}) if isinstance(result.get("summary", {}), dict) else {}
        s = f"总计 {summary.get('total', len(rows))}，成功 {summary.get('success', 0)}，失败 {summary.get('failed', 0)}，跳过 {summary.get('skipped', 0)}"
        if lines:
            if detailed:
                return s + "\n" + "\n".join(lines[: min(12, len(lines))])
            return s + "\n" + "\n".join(lines[:4])
        return s
    if result.get("stdout"):
        return (result.get("stdout") or "").strip()
    if result.get("error"):
        return f"执行失败：{result.get('error')}"
    if result.get("code"):
        code = str(result.get("code") or "").strip()
        first = code.splitlines()[:3]
        return "执行成功（无 stdout）。代码片段：" + " | ".join(first)
    if result.get("reflection"):
        reflection = result.get("reflection", {}) if isinstance(result.get("reflection", {}), dict) else {}
        fp = str(reflection.get("failure_pattern", "") or "").strip()
        if fp:
            return f"执行完成。反思发现的问题模式：{fp}"
    return "执行完成（无可展示输出）。"


def _extract_detailed_reply(result: dict) -> str:
    base = _extract_reply(result, detailed=True)
    extra: list[str] = []
    reflection = result.get("reflection", {}) if isinstance(result.get("reflection", {}), dict) else {}
    if reflection:
        task_type = str(reflection.get("task_type", "") or "").strip()
        fp = str(reflection.get("failure_pattern", "") or "").strip()
        if task_type:
            extra.append(f"reflection.task_type={task_type}")
        if fp:
            extra.append(f"reflection.failure_pattern={fp}")
    po = result.get("prompt_optimization", {}) if isinstance(result.get("prompt_optimization", {}), dict) else {}
    if po:
        extra.append(f"prompt_optimization.applied={bool(po.get('applied', False))}")
        if po.get("reason"):
            extra.append(f"prompt_optimization.reason={po.get('reason')}")
    return base + ("\n\n" + "\n".join(extra) if extra else "")


def _build_market() -> PluginMarketplace:
    cfg = load_config()
    plugins = cfg.get("plugins", {}) if isinstance(cfg.get("plugins", {}), dict) else {}
    tp = plugins.get("third_party", {}) if isinstance(plugins.get("third_party", {}), dict) else {}
    market_cfg = tp.get("market", {}) if isinstance(tp.get("market", {}), dict) else {}
    security = market_cfg.get("security", {}) if isinstance(market_cfg.get("security", {}), dict) else {}
    allowed_domains = security.get("allowed_index_domains", [])
    if not isinstance(allowed_domains, list):
        allowed_domains = []
    return PluginMarketplace(
        third_party_dir=tp.get("dir", str(Path.cwd() / "plugins" / "third_party")),
        index_url=str(market_cfg.get("index_url", "") or ""),
        index_file=market_cfg.get("index_file", "data/plugin_market_index.json"),
        installed_file=market_cfg.get("installed_file", "data/plugin_market_installed.json"),
        allowed_index_domains=[str(x) for x in allowed_domains],
        index_sha256=str(security.get("index_sha256", "") or ""),
        plugin_hash_required=bool(security.get("plugin_hash_required", False)),
    )


def _event_trace_tool() -> EventTraceReplayer:
    cfg = load_config()
    plugins = cfg.get("plugins", {}) if isinstance(cfg.get("plugins", {}), dict) else {}
    rec = plugins.get("event_recorder", {}) if isinstance(plugins.get("event_recorder", {}), dict) else {}
    trace_file = rec.get("trace_file", "data/runtime_events.jsonl")
    return EventTraceReplayer(trace_file)


def _mcp_capabilities_catalog(config_path: str | None = None) -> dict:
    cfg = load_config(config_path)
    capability_cfg = cfg.get("capabilities", {}) if isinstance(cfg.get("capabilities", {}), dict) else {}
    rows = build_mcp_server_configs(capability_cfg.get("mcp_servers", []) if isinstance(capability_cfg.get("mcp_servers", []), list) else [])
    servers: list[dict] = []
    for s in rows:
        item = {"name": s.name, "endpoint": s.endpoint, "tools": [], "error": ""}
        try:
            tools = MCPCapabilityAdapter(s).load_tools()
            item["tools"] = [
                {
                    "name": t.name,
                    "source": t.source,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
        except Exception as e:
            item["error"] = str(e)[:240]
        servers.append(item)
    return {"servers": servers, "count": len(servers)}


def _build_session_manager(config_path: str | None = None) -> SessionManager:
    cfg = load_config(config_path)
    chat_cfg = cfg.get("chat", {}) if isinstance(cfg.get("chat", {}), dict) else {}
    session_file = chat_cfg.get("session_store_file")
    if not isinstance(session_file, str) or not session_file.strip():
        session_file = str((get_data_dir(cfg) / "chat_sessions.json").resolve())
    return SessionManager(
        SessionStorage(session_file),
        keep_recent_messages=int(chat_cfg.get("keep_recent_messages", 10)),
        compress_threshold=int(chat_cfg.get("compress_threshold", 14)),
        max_context_chars=int(chat_cfg.get("max_context_chars", 3000)),
        max_summary_chars=int(chat_cfg.get("max_summary_chars", 1200)),
    )


def _build_chat_memory_manager(config_path: str | None = None) -> MemoryManager | None:
    cfg = load_config(config_path)
    chat_cfg = cfg.get("chat", {}) if isinstance(cfg.get("chat", {}), dict) else {}
    long_term = chat_cfg.get("long_term", {}) if isinstance(chat_cfg.get("long_term", {}), dict) else {}
    if not bool(long_term.get("enabled", True)):
        return None
    paths = cfg.get("paths", {}) if isinstance(cfg.get("paths", {}), dict) else {}
    sqlite_db = str(paths.get("sqlite_db", str((get_data_dir(cfg) / "gtos.db").resolve())))
    memory_cfg = cfg.get("memory", {}).get("vector_store", {}) if isinstance(cfg.get("memory", {}).get("vector_store", {}), dict) else {}
    vector_store = None
    try:
        if bool(memory_cfg.get("enabled", True)):
            backend = str(memory_cfg.get("backend", "keyword"))
            persist = long_term.get("vector_persist_file") or memory_cfg.get("persist_path") or str((get_data_dir(cfg) / "chat_vectors.json").resolve())
            vector_store = get_vector_store(
                backend=backend,
                persist_path=persist,
                embedding_config=memory_cfg.get("embedding", {}),
                llm_config=cfg.get("llm", {}),
            )
    except Exception:
        vector_store = None
    return MemoryManager(sqlite_db=sqlite_db, vector_store=vector_store, skill_store=None)


def _recall_conversation_memories(memory_manager: MemoryManager | None, session_id: str, message: str, top_k: int = 3) -> list[str]:
    if memory_manager is None:
        return []
    q = str(message or "").strip()
    if not q:
        return []
    try:
        hits = memory_manager.query(q, top_k=max(1, int(top_k) * 2))
    except Exception:
        return []
    semantic = hits.get("semantic", []) if isinstance(hits, dict) else []
    if (not isinstance(semantic, list) or not semantic) and memory_manager is not None:
        try:
            semantic = memory_manager.recent_semantic(limit=max(6, int(top_k) * 8))
        except Exception:
            semantic = []
    if not isinstance(semantic, list):
        return []
    rows: list[str] = []
    for h in semantic:
        if not isinstance(h, dict):
            continue
        tags = h.get("tags", {}) if isinstance(h.get("tags", {}), dict) else {}
        sid = str(tags.get("session_id", "") or "").strip()
        if sid and sid != session_id:
            continue
        txt = str(h.get("summary", "") or "").strip()
        if txt:
            rows.append(txt[:220])
        if len(rows) >= max(1, int(top_k)):
            break
    return rows


def _persist_conversation_memory(memory_manager: MemoryManager | None, session_id: str, user_message: str, assistant_reply: str) -> None:
    if memory_manager is None:
        return
    user_text = str(user_message or "").replace("\n", " ").strip()[:180]
    assistant_text = str(assistant_reply or "").replace("\n", " ").strip()[:240]
    if not user_text and not assistant_text:
        return
    summary = f"用户: {user_text} | 助手: {assistant_text}".strip(" |")
    try:
        memory_manager.write_semantic(
            summary=summary,
            tags={"session_id": session_id, "type": "conversation_turn"},
            source="chat_session",
        )
    except Exception:
        return


def _compose_task_prompt(message: str, context: str, recalled: list[str] | None = None) -> str:
    msg = str(message or "").strip()
    ctx = str(context or "").strip()
    recalled_lines = [str(x).strip() for x in (recalled or []) if str(x).strip()]
    if not ctx and not recalled_lines:
        return msg
    chunks: list[str] = []
    if ctx:
        chunks.append("[Conversation History]")
        chunks.append(ctx)
    if recalled_lines:
        chunks.append("[Relevant Past Conversation]")
        for row in recalled_lines[:6]:
            chunks.append(f"- {row}")
    chunks.append("[Current Task]")
    chunks.append(msg)
    return "\n".join(chunks)


class ChatHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        if self.path.startswith("/api/health"):
            self._send_json(200, {"ok": True, "service": "gtos-chat-api"})
            return
        if self.path.startswith("/api/runtime/status"):
            cfg = load_config()
            runtime = cfg.get("runtime", {}) if isinstance(cfg.get("runtime", {}), dict) else {}
            plugins = cfg.get("plugins", {}) if isinstance(cfg.get("plugins", {}), dict) else {}
            tp = plugins.get("third_party", {}) if isinstance(plugins.get("third_party", {}), dict) else {}
            self._send_json(
                200,
                {
                    "ok": True,
                    "runtime": {
                        "react_enabled": bool(runtime.get("react_enabled", False)),
                        "reflection_enabled": bool(runtime.get("reflection_enabled", False)),
                        "multi_agent_enabled": bool((runtime.get("multi_agent", {}) or {}).get("enabled", False))
                        if isinstance(runtime.get("multi_agent", {}), dict)
                        else False,
                    },
                    "plugins": {
                        "enabled": plugins.get("enabled", []),
                        "third_party_dir": tp.get("dir", str(Path.cwd() / "plugins" / "third_party")),
                        "third_party_enabled": bool(tp.get("enabled", True)),
                    },
                },
            )
            return
        if self.path.startswith("/api/plugins/market"):
            market = _build_market()
            self._send_json(200, {"ok": True, **market.get_market()})
            return
        if self.path.startswith("/api/plugins/versions"):
            q = parse.urlparse(self.path).query
            params = parse.parse_qs(q)
            name = str((params.get("name") or [""])[0] or "").strip()
            market = _build_market()
            self._send_json(200, {"ok": True, "name": name, "versions": market.list_versions(name)})
            return
        if self.path.startswith("/api/events/summary"):
            tool = _event_trace_tool()
            self._send_json(200, {"ok": True, **tool.summary()})
            return
        if self.path.startswith("/api/events/recent"):
            q = parse.urlparse(self.path).query
            params = parse.parse_qs(q)
            limit_raw = str((params.get("limit") or ["100"])[0] or "100")
            try:
                limit = max(1, min(500, int(limit_raw)))
            except Exception:
                limit = 100
            tool = _event_trace_tool()
            self._send_json(200, {"ok": True, "events": tool.recent(limit=limit), "limit": limit})
            return
        if self.path.startswith("/api/capabilities/mcp"):
            q = parse.urlparse(self.path).query
            params = parse.parse_qs(q)
            config_path = str((params.get("config_path") or [""])[0] or "").strip() or None
            self._send_json(200, {"ok": True, **_mcp_capabilities_catalog(config_path=config_path)})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path.startswith("/api/plugins/install"):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            plugin_name = str(payload.get("name", "")).strip()
            if not plugin_name:
                self._send_json(400, {"ok": False, "error": "plugin_name_required"})
                return
            market = _build_market()
            installed = market.install(plugin_name)
            if not installed.get("ok"):
                self._send_json(400, {"ok": False, **installed})
                return
            self._send_json(200, {"ok": True, **installed})
            return
        if self.path.startswith("/api/plugins/uninstall"):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            plugin_name = str(payload.get("name", "")).strip()
            market = _build_market()
            out = market.uninstall(plugin_name)
            if not out.get("ok"):
                self._send_json(400, {"ok": False, **out})
                return
            self._send_json(200, {"ok": True, **out})
            return
        if self.path.startswith("/api/plugins/toggle"):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            plugin_name = str(payload.get("name", "")).strip()
            enabled = bool(payload.get("enabled", True))
            market = _build_market()
            out = market.set_enabled(plugin_name, enabled=enabled)
            if not out.get("ok"):
                self._send_json(400, {"ok": False, **out})
                return
            self._send_json(200, {"ok": True, **out})
            return
        if self.path.startswith("/api/plugins/rollback"):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            plugin_name = str(payload.get("name", "")).strip()
            version = str(payload.get("version", "")).strip()
            market = _build_market()
            out = market.rollback(plugin_name, version=version)
            if not out.get("ok"):
                self._send_json(400, {"ok": False, **out})
                return
            self._send_json(200, {"ok": True, **out})
            return
        if self.path.startswith("/api/plugins/reload"):
            # Hot-reload behavior: each execute_once call rebuilds plugin registry from disk.
            # This endpoint validates current discoverability and returns immediate state.
            market = _build_market()
            installed = market.list_installed()
            self._send_json(200, {"ok": True, "reloaded": True, "installed_count": len(installed), "installed": installed})
            return

        if not self.path.startswith("/api/chat"):
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return
        message = str(payload.get("message", "")).strip()
        config_path = payload.get("config_path")
        conversation_id = str(payload.get("conversation_id", "") or "").strip()
        if not message:
            self._send_json(400, {"ok": False, "error": "message_required"})
            return
        try:
            session_manager = _build_session_manager(config_path=config_path)
            memory_manager = _build_chat_memory_manager(config_path=config_path)
            cfg = load_config(config_path)
            long_term_cfg = cfg.get("chat", {}).get("long_term", {}) if isinstance(cfg.get("chat", {}).get("long_term", {}), dict) else {}
            conversation_id = session_manager.ensure_session(conversation_id if conversation_id else None)
            context = session_manager.build_context(conversation_id)
            recalled = _recall_conversation_memories(
                memory_manager=memory_manager,
                session_id=conversation_id,
                message=message,
                top_k=int(long_term_cfg.get("top_k", 3)),
            )
            final_task = _compose_task_prompt(message, context, recalled=recalled)

            out = execute_once(config_path=config_path, task_override=final_task)
            result = out.get("result", {})
            detail_mode = bool(payload.get("detail_mode", False))
            reply = _extract_detailed_reply(result) if detail_mode else _extract_reply(result)
            session_manager.append_message(conversation_id, "user", message)
            session_manager.append_message(conversation_id, "assistant", reply)
            _persist_conversation_memory(memory_manager, conversation_id, message, reply)
            self._send_json(
                200,
                {
                    "ok": True,
                    "reply": reply,
                    "detail_mode": detail_mode,
                    "conversation_id": conversation_id,
                    "context_used": bool(context),
                    "long_term_used": bool(recalled),
                    "result": result,
                    "assessment": out.get("assessment", {}),
                    "optimizer": out.get("optimizer_state", {}),
                },
            )
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})


def main() -> None:
    parser = argparse.ArgumentParser(description="GTOS 本地 Chat API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ChatHandler)
    print(f"GTOS Chat API running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
