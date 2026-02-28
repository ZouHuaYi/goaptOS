"""MCP adapter: load remote tools as local capabilities."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib import parse, request

from gtos.core.capability.base import ToolCapability

logger = logging.getLogger("gtos")


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    endpoint: str
    timeout_seconds: int = 8
    allowed_tools: list[str] | None = None
    allowed_actions: list[str] | None = None
    headers: dict[str, str] | None = None


class MCPClient:
    """Minimal MCP-over-HTTP client with JSON-RPC first, REST fallback."""

    def __init__(self, cfg: MCPServerConfig) -> None:
        self._cfg = cfg
        self._rpc_id = 1

    def list_tools(self) -> list[dict[str, Any]]:
        # 1) JSON-RPC
        try:
            payload = self._rpc("tools/list", {})
            tools = payload.get("tools", []) if isinstance(payload, dict) else []
            if isinstance(tools, list):
                return [t for t in tools if isinstance(t, dict)]
        except Exception:
            pass
        # 2) REST fallback
        payload = self._http("GET", "/tools", None)
        tools = payload.get("tools", []) if isinstance(payload, dict) else []
        return [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else []

    def call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        # 1) JSON-RPC
        try:
            payload = self._rpc("tools/call", {"name": tool_name, "arguments": params or {}})
            return payload
        except Exception:
            pass
        # 2) REST fallback
        return self._http("POST", f"/tools/{parse.quote(tool_name)}/call", {"arguments": params or {}})

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": method,
            "params": params,
        }
        self._rpc_id += 1
        payload = self._http("POST", "", body)
        if not isinstance(payload, dict):
            raise RuntimeError("mcp rpc invalid response")
        if payload.get("error"):
            raise RuntimeError(str(payload.get("error")))
        return payload.get("result", {})

    def _http(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        url = str(self._cfg.endpoint or "").rstrip("/")
        if path:
            if not path.startswith("/"):
                path = "/" + path
            url = url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if isinstance(self._cfg.headers, dict):
            for k, v in self._cfg.headers.items():
                headers[str(k)] = str(v)
        req = request.Request(url, data=data, method=method, headers=headers)
        with request.urlopen(req, timeout=max(1, int(self._cfg.timeout_seconds))) as resp:
            raw = resp.read().decode("utf-8")
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}


class MCPToolWrapper(ToolCapability):
    def __init__(
        self,
        *,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any] | None,
        client: MCPClient,
        allowed_tools: list[str] | None = None,
        allowed_actions: list[str] | None = None,
        audit_hook: Any | None = None,
    ) -> None:
        name = f"mcp:{server_name}:{tool_name}"
        super().__init__(
            name=name,
            source=f"mcp:{server_name}",
            description=description or "",
            input_schema=input_schema or {"type": "object", "properties": {}},
            constraints={
                "allowed_tools": list(allowed_tools or []),
                "allowed_actions": list(allowed_actions or []),
            },
        )
        self._tool_name = tool_name
        self._client = client
        self._allowed_tools = set([x.strip() for x in (allowed_tools or []) if str(x).strip()])
        self._allowed_actions = set([x.strip() for x in (allowed_actions or []) if str(x).strip()])
        self._audit_hook = audit_hook

    def execute(self, params: dict[str, Any] | None = None) -> Any:
        started = time.perf_counter()
        ok = False
        err = ""
        if self._allowed_tools and self._tool_name not in self._allowed_tools:
            err = f"mcp_tool_blocked: {self._tool_name}"
            self._emit_audit(params or {}, ok=False, error=err, latency_ms=(time.perf_counter() - started) * 1000)
            raise PermissionError(err)
        action = str((params or {}).get("action", "")).strip()
        if action and self._allowed_actions and action not in self._allowed_actions:
            err = f"mcp_action_blocked: {action}"
            self._emit_audit(params or {}, ok=False, error=err, latency_ms=(time.perf_counter() - started) * 1000)
            raise PermissionError(err)
        try:
            out = self._client.call_tool(self._tool_name, params or {})
            ok = True
            return out
        except Exception as e:
            err = str(e)
            raise
        finally:
            self._emit_audit(params or {}, ok=ok, error=err, latency_ms=(time.perf_counter() - started) * 1000)

    def _emit_audit(self, params: dict[str, Any], *, ok: bool, error: str, latency_ms: float) -> None:
        if not callable(self._audit_hook):
            return
        try:
            self._audit_hook(
                {
                    "event": "mcp_tool_call",
                    "tool": self._tool_name,
                    "capability": self.name,
                    "source": self.source,
                    "ok": bool(ok),
                    "latency_ms": round(float(latency_ms), 2),
                    "error": str(error or "")[:240],
                    "params_preview": str(params)[:500],
                }
            )
        except Exception:
            return


class MCPCapabilityAdapter:
    def __init__(self, cfg: MCPServerConfig, client: MCPClient | None = None, audit_hook: Any | None = None) -> None:
        self._cfg = cfg
        self._client = client or MCPClient(cfg)
        self._audit_hook = audit_hook

    def load_tools(self) -> list[MCPToolWrapper]:
        tools = self._client.list_tools()
        out: list[MCPToolWrapper] = []
        for t in tools:
            tool_name = str(t.get("name", "")).strip()
            if not tool_name:
                continue
            desc = str(t.get("description", "") or "")
            schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else t.get("schema", {})
            if not isinstance(schema, dict):
                schema = {}
            out.append(
                MCPToolWrapper(
                    server_name=self._cfg.name,
                    tool_name=tool_name,
                    description=desc,
                    input_schema=schema,
                    client=self._client,
                    allowed_tools=self._cfg.allowed_tools,
                    allowed_actions=self._cfg.allowed_actions,
                    audit_hook=self._audit_hook,
                )
            )
        logger.info("mcp adapter loaded tools: server=%s count=%s", self._cfg.name, len(out))
        return out


def build_mcp_server_configs(raw: list[dict[str, Any]] | None = None) -> list[MCPServerConfig]:
    rows = raw if isinstance(raw, list) else []
    out: list[MCPServerConfig] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        endpoint = str(item.get("endpoint", "")).strip()
        if not name or not endpoint:
            continue
        permissions = item.get("permissions", {}) if isinstance(item.get("permissions", {}), dict) else {}
        allowed_tools = permissions.get("allowed_tools", [])
        allowed_actions = permissions.get("allowed_actions", [])
        headers = item.get("headers", {})
        out.append(
            MCPServerConfig(
                name=name,
                endpoint=endpoint,
                timeout_seconds=int(item.get("timeout_seconds", 8)),
                allowed_tools=[str(x) for x in allowed_tools] if isinstance(allowed_tools, list) else None,
                allowed_actions=[str(x) for x in allowed_actions] if isinstance(allowed_actions, list) else None,
                headers={str(k): str(v) for k, v in headers.items()} if isinstance(headers, dict) else None,
            )
        )
    return out
