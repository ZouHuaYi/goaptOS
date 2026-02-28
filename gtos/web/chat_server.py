"""Simple local chat API for GTOS web UI."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse

from gtos.config import load_config
from gtos.main import execute_once
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
        if not message:
            self._send_json(400, {"ok": False, "error": "message_required"})
            return
        try:
            out = execute_once(config_path=config_path, task_override=message)
            result = out.get("result", {})
            detail_mode = bool(payload.get("detail_mode", False))
            reply = _extract_detailed_reply(result) if detail_mode else _extract_reply(result)
            self._send_json(
                200,
                {
                    "ok": True,
                    "reply": reply,
                    "detail_mode": detail_mode,
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
