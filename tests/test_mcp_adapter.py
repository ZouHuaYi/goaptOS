from gtos.core.capability import CapabilityRuntimeRegistry, MCPCapabilityAdapter, MCPServerConfig, build_mcp_server_configs


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self):
        return [
            {
                "name": "figma.export_node",
                "description": "export figma node",
                "inputSchema": {"type": "object", "properties": {"nodeId": {"type": "string"}}},
            }
        ]

    def call_tool(self, tool_name: str, params: dict):
        self.calls.append((tool_name, params))
        return {"ok": True, "tool": tool_name, "params": params}


def test_mcp_adapter_load_and_execute() -> None:
    cfg = MCPServerConfig(name="figma", endpoint="http://localhost:4000")
    fake = _FakeClient()
    adapter = MCPCapabilityAdapter(cfg, client=fake)  # type: ignore[arg-type]
    tools = adapter.load_tools()
    assert len(tools) == 1
    reg = CapabilityRuntimeRegistry()
    reg.register(tools[0])
    out = reg.execute("mcp:figma:figma.export_node", {"nodeId": "1:2"})
    assert out.get("ok") is True
    assert fake.calls[0][0] == "figma.export_node"


def test_mcp_adapter_permission_block_action() -> None:
    cfg = MCPServerConfig(name="figma", endpoint="http://localhost:4000", allowed_actions=["read"])
    fake = _FakeClient()
    tool = MCPCapabilityAdapter(cfg, client=fake).load_tools()[0]  # type: ignore[arg-type]
    blocked = False
    try:
        tool.execute({"action": "write", "nodeId": "1:2"})
    except PermissionError:
        blocked = True
    assert blocked is True


def test_mcp_adapter_emits_audit_hook() -> None:
    cfg = MCPServerConfig(name="figma", endpoint="http://localhost:4000")
    fake = _FakeClient()
    audits: list[dict] = []
    tool = MCPCapabilityAdapter(cfg, client=fake, audit_hook=lambda e: audits.append(e)).load_tools()[0]  # type: ignore[arg-type]
    out = tool.execute({"nodeId": "1:2"})
    assert out.get("ok") is True
    assert len(audits) >= 1
    assert audits[-1].get("event") == "mcp_tool_call"
    assert audits[-1].get("ok") is True


def test_build_mcp_server_configs_parse_permissions() -> None:
    rows = build_mcp_server_configs(
        [
            {
                "name": "figma",
                "endpoint": "http://localhost:4000",
                "permissions": {
                    "allowed_tools": ["figma.export_node"],
                    "allowed_actions": ["read_file"],
                },
                "timeout_seconds": 9,
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0].name == "figma"
    assert rows[0].allowed_tools == ["figma.export_node"]
    assert rows[0].allowed_actions == ["read_file"]
