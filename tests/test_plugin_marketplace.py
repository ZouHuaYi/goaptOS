import json
import hashlib
import time
from pathlib import Path

from gtos.plugins.marketplace import PluginMarketplace


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_marketplace_loads_index_and_installs_local_plugin() -> None:
    ts = int(time.time() * 1000)
    root = Path(f"data/_unit_market_{ts}")
    src = root / "registry" / "demo_plugin_src"
    tp = root / "third_party"
    idx = root / "plugin_market_index.json"
    installed = root / "plugin_market_installed.json"

    _write(
        src / "plugin.yaml",
        "\n".join(
            [
                "name: demo_plugin",
                "events:",
                "  - on_action",
                "class: Plugin",
                "source: plugin.py",
                "enabled: true",
            ]
        ),
    )
    _write(
        src / "plugin.py",
        "\n".join(
            [
                "from gtos.core.interfaces.plugin import PluginLifecycle",
                "class Plugin(PluginLifecycle):",
                "    pass",
            ]
        ),
    )
    index_payload = {
        "plugins": [
            {
                "name": "demo_plugin",
                "version": "0.0.1",
                "compatibility": ">=0.1.0",
                "description": "demo",
                "source_dir": str(src.resolve()),
            }
        ]
    }
    _write(idx, json.dumps(index_payload, ensure_ascii=False))

    market = PluginMarketplace(
        third_party_dir=tp,
        index_url="",
        index_file=idx,
        installed_file=installed,
    )
    listing = market.get_market()
    assert len(listing["plugins"]) == 1
    assert listing["plugins"][0]["name"] == "demo_plugin"

    out = market.install("demo_plugin")
    assert out["ok"] is True
    assert (tp / "demo_plugin" / "plugin.yaml").exists()

    installed_rows = market.list_installed()
    names = {str(x.get("name", "")) for x in installed_rows}
    assert "demo_plugin" in names

    toggled = market.set_enabled("demo_plugin", enabled=False)
    assert toggled["ok"] is True
    manifest_text = (tp / "demo_plugin" / "plugin.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in manifest_text

    rolled = market.rollback("demo_plugin")
    assert rolled["ok"] is True

    removed = market.uninstall("demo_plugin")
    assert removed["ok"] is True
    assert not (tp / "demo_plugin").exists()


def test_marketplace_hash_verification() -> None:
    ts = int(time.time() * 1000)
    root = Path(f"data/_unit_market_hash_{ts}")
    src = root / "registry" / "demo_plugin_src"
    tp = root / "third_party"
    idx = root / "plugin_market_index.json"
    installed = root / "plugin_market_installed.json"
    _write(src / "plugin.yaml", "name: demo_plugin\nenabled: true\n")
    _write(src / "plugin.py", "class Plugin:\n    pass\n")

    h = hashlib.sha256()
    for f in sorted(src.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(src)).replace("\\", "/")
            h.update(rel.encode("utf-8"))
            h.update(f.read_bytes())
    source_hash = h.hexdigest().lower()
    index_payload = {
        "plugins": [
            {
                "name": "demo_plugin",
                "version": "0.0.2",
                "compatibility": ">=0.1.0",
                "source_dir": str(src.resolve()),
                "source_hash": source_hash,
            }
        ]
    }
    _write(idx, json.dumps(index_payload, ensure_ascii=False))

    market = PluginMarketplace(
        third_party_dir=tp,
        index_file=idx,
        installed_file=installed,
        plugin_hash_required=True,
    )
    out = market.install("demo_plugin")
    assert out["ok"] is True


def test_marketplace_domain_whitelist_blocks_remote_index() -> None:
    ts = int(time.time() * 1000)
    root = Path(f"data/_unit_market_domain_{ts}")
    market = PluginMarketplace(
        third_party_dir=root / "tp",
        index_url="https://example.com/plugins.json",
        index_file=root / "index.json",
        installed_file=root / "installed.json",
        allowed_index_domains=["raw.githubusercontent.com"],
    )
    data = market.get_market()
    assert data["plugins"] == []
    assert data.get("last_error") in {"index_domain_not_allowed", "index_fetch_failed"}
