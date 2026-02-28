import time
from pathlib import Path

from gtos.executor.plugin_manager import PluginManager
from gtos.plugins.loader import ThirdPartyPluginLoader
from gtos.plugins.sdk import parse_plugin_manifest


def _prepare_plugin_root() -> Path:
    root = Path(f"data/_unit_plugins_{int(time.time() * 1000)}")
    plugin_dir = root / "sample_plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        "\n".join(
            [
                "name: sample_plugin",
                "events:",
                "  - on_action",
                "  - on_reflection_complete",
                "class: Plugin",
                "source: plugin.py",
                "enabled: true",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from gtos.core.interfaces.plugin import PluginLifecycle",
                "",
                "class Plugin(PluginLifecycle):",
                "    def __init__(self, **kwargs):",
                "        self._kwargs = kwargs",
                "    def pre_execute(self, task_prompt: str) -> str:",
                "        return task_prompt + ' [tp]'",
                "    def on_event(self, event_name: str, payload: dict) -> None:",
                "        payload.setdefault('_seen', []).append(event_name)",
            ]
        ),
        encoding="utf-8",
    )
    return root


def test_parse_plugin_manifest_with_events() -> None:
    root = _prepare_plugin_root()
    m = parse_plugin_manifest(root / "sample_plugin" / "plugin.yaml")
    assert m.name == "sample_plugin"
    assert m.class_name == "Plugin"
    assert "on_action" in m.events


def test_third_party_loader_discover_and_register() -> None:
    root = _prepare_plugin_root()
    loader = ThirdPartyPluginLoader(root_dir=root)
    manifests = loader.discover()
    assert len(manifests) == 1

    plugin = loader.instantiate(manifests[0], context={"config": {"x": 1}})
    assert plugin is not None

    pm = PluginManager()
    pm.register(plugin)
    pm.start()
    out = pm.apply_pre_execute("hello")
    payload = pm.event_bus.emit("on_reflection_complete", {"x": 1})
    pm.shutdown()

    assert out.endswith("[tp]")
    assert "on_reflection_complete" in payload.get("_seen", [])

