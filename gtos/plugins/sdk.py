"""Plugin SDK primitives: manifest model and lightweight plugin.yaml parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PluginManifest:
    name: str
    events: list[str]
    module: str
    class_name: str
    source: str
    enabled: bool
    manifest_path: Path


def parse_plugin_manifest(path: str | Path) -> PluginManifest:
    p = Path(path)
    data = _parse_minimal_yaml(p.read_text(encoding="utf-8"))
    name = str(data.get("name", p.parent.name)).strip() or p.parent.name
    events = data.get("events", [])
    if not isinstance(events, list):
        events = []
    events = [str(x).strip() for x in events if str(x).strip()]
    module = str(data.get("module", "") or "").strip()
    class_name = str(data.get("class", "") or "").strip()
    source = str(data.get("source", "plugin.py") or "plugin.py").strip()
    enabled = bool(data.get("enabled", True))

    # compatibility: class_path: package.module:ClassName
    class_path = str(data.get("class_path", "") or "").strip()
    if class_path and ":" in class_path:
        module, class_name = class_path.split(":", 1)
        module = module.strip()
        class_name = class_name.strip()

    if not class_name:
        class_name = "Plugin"
    return PluginManifest(
        name=name,
        events=events,
        module=module,
        class_name=class_name,
        source=source,
        enabled=enabled,
        manifest_path=p,
    )


def _parse_minimal_yaml(text: str) -> dict:
    """Minimal YAML parser supporting:
    key: value
    key:
      - item1
      - item2
    """
    out: dict = {}
    current_list_key: str | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            if current_list_key:
                out.setdefault(current_list_key, []).append(_coerce_scalar(line[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            out[key] = []
            current_list_key = key
            continue
        out[key] = _coerce_scalar(value)
        current_list_key = None
    return out


def _coerce_scalar(value: str):
    v = (value or "").strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return v

