"""Simple local chat API for GTOS web UI."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gtos.main import execute_once


def _extract_reply(result: dict) -> str:
    if result.get("rejected"):
        return f"任务被拒绝：{result.get('reason')}（风险：{result.get('risk')}）"
    if result.get("results"):
        outs = []
        for r in result.get("results", []):
            txt = (r.get("stdout") or "").strip()
            if txt:
                outs.append(txt)
        if outs:
            return "\n".join(outs[-2:])
        return "任务执行完成。"
    if result.get("stdout"):
        return (result.get("stdout") or "").strip()
    if result.get("error"):
        return f"执行失败：{result.get('error')}"
    return "任务执行完成。"


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
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
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
            reply = _extract_reply(result)
            self._send_json(
                200,
                {
                    "ok": True,
                    "reply": reply,
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

