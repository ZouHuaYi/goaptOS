"""Dynamic third-party plugin loader."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Any

from gtos.plugins.sdk import PluginManifest, parse_plugin_manifest

logger = logging.getLogger("gtos")


class ThirdPartyPluginLoader:
    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir)

    def discover(self) -> list[PluginManifest]:
        if not self._root.exists():
            return []
        manifests: list[PluginManifest] = []
        for yml in self._root.glob("*/plugin.yaml"):
            try:
                m = parse_plugin_manifest(yml)
                if m.enabled:
                    manifests.append(m)
            except Exception as e:
                logger.warning("plugin manifest parse failed: %s", str(e)[:240])
        manifests.sort(key=lambda x: x.name)
        return manifests

    def instantiate(self, manifest: PluginManifest, context: dict[str, Any] | None = None) -> Any | None:
        ctx = context or {}
        try:
            cls = self._resolve_class(manifest)
        except Exception as e:
            logger.warning("plugin class resolve failed: plugin=%s err=%s", manifest.name, str(e)[:240])
            return None
        try:
            # Best-effort constructor injection by kwargs.
            return cls(**ctx)
        except TypeError:
            try:
                return cls()
            except Exception as e:
                logger.warning("plugin init failed: plugin=%s err=%s", manifest.name, str(e)[:240])
                return None
        except Exception as e:
            logger.warning("plugin init failed: plugin=%s err=%s", manifest.name, str(e)[:240])
            return None

    def _resolve_class(self, manifest: PluginManifest):
        if manifest.module:
            mod = importlib.import_module(manifest.module)
            return getattr(mod, manifest.class_name)
        src = (manifest.manifest_path.parent / manifest.source).resolve()
        mod_name = f"gtos_thirdparty_{manifest.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(mod_name, src)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"invalid plugin source: {src}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, manifest.class_name)

