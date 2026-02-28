import time
from pathlib import Path

from gtos.executor.plugin_manager import PluginManager
from gtos.core.events import EventName, ReflectionCompletePayload
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
                "from gtos.core.events import EventName, TaskPromptActionPayload",
                "",
                "class Plugin(PluginLifecycle):",
                "    def __init__(self, **kwargs):",
                "        self._kwargs = kwargs",
                "    def on_event(self, event) -> None:",
                "        if event.name == EventName.ON_ACTION and isinstance(event.payload, TaskPromptActionPayload):",
                "            event.payload.task_prompt = str(event.payload.task_prompt) + ' [tp]'",
                "        if hasattr(event.payload, 'result') and isinstance(getattr(event.payload, 'result', None), dict):",
                "            event.payload.result.setdefault('_seen', []).append(event.name.value)",
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
    evt = pm.event_bus.emit_name(
        EventName.ON_REFLECTION_COMPLETE,
        ReflectionCompletePayload(task="t", reflection={}, result={"x": 1}),
    )
    pm.shutdown()

    assert out.endswith("[tp]")
    assert "on_reflection_complete" in evt.payload.result.get("_seen", [])
