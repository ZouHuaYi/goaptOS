from gtos.web.chat_server import _mcp_capabilities_catalog


def test_mcp_catalog_without_servers_returns_empty() -> None:
    out = _mcp_capabilities_catalog(config_path="config.custom.json")
    assert isinstance(out, dict)
    assert out.get("count") == 0
    assert out.get("servers") == []

