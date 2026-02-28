"""Plugin marketplace index and install-state helpers."""

from __future__ import annotations

import json
import hashlib
import shutil
import time
from pathlib import Path
from typing import Any
from urllib import parse, request

from gtos import __version__ as gtos_version
from gtos.plugins.sdk import parse_plugin_manifest


class PluginMarketplace:
    def __init__(
        self,
        *,
        third_party_dir: str | Path,
        index_url: str = "",
        index_file: str | Path = "data/plugin_market_index.json",
        installed_file: str | Path = "data/plugin_market_installed.json",
        allowed_index_domains: list[str] | None = None,
        index_sha256: str = "",
        plugin_hash_required: bool = False,
    ) -> None:
        self._third_party_dir = Path(third_party_dir)
        self._versions_dir = self._third_party_dir / ".versions"
        self._index_url = str(index_url or "").strip()
        self._index_file = Path(index_file)
        self._installed_file = Path(installed_file)
        self._allowed_index_domains = [str(x).strip().lower() for x in (allowed_index_domains or []) if str(x).strip()]
        self._index_sha256 = str(index_sha256 or "").strip().lower()
        self._plugin_hash_required = bool(plugin_hash_required)
        self._index_file.parent.mkdir(parents=True, exist_ok=True)
        self._installed_file.parent.mkdir(parents=True, exist_ok=True)
        self._third_party_dir.mkdir(parents=True, exist_ok=True)
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._last_error = ""

    def get_market(self) -> dict[str, Any]:
        index = self._load_index()
        installed = self.list_installed()
        return {
            "gtos_version": gtos_version,
            "index_source": self._index_url or str(self._index_file),
            "plugins": index,
            "installed": installed,
            "security": {
                "allowed_index_domains": self._allowed_index_domains,
                "index_sha256_set": bool(self._index_sha256),
                "plugin_hash_required": self._plugin_hash_required,
            },
            "last_error": self._last_error,
            "updated_ts": time.time(),
        }

    def list_installed(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if self._third_party_dir.exists():
            for yml in self._third_party_dir.glob("*/plugin.yaml"):
                try:
                    m = parse_plugin_manifest(yml)
                    rows.append(
                        {
                            "name": m.name,
                            "enabled": m.enabled,
                            "events": m.events,
                            "manifest_path": str(yml.resolve()),
                            "status": "installed",
                        }
                    )
                except Exception:
                    continue
        meta = self._read_json_file(self._installed_file)
        extra = meta.get("installed", []) if isinstance(meta, dict) else []
        if isinstance(extra, list):
            names = {str(x.get("name", "")) for x in rows}
            for x in extra:
                if not isinstance(x, dict):
                    continue
                name = str(x.get("name", ""))
                if name and name not in names:
                    rows.append(dict(x))
        rows.sort(key=lambda x: str(x.get("name", "")))
        return rows

    def install(self, plugin_name: str) -> dict[str, Any]:
        name = self._normalize_plugin_name(plugin_name)
        if not name:
            return {"ok": False, "error": "plugin_name_required"}
        index = self._load_index()
        matched = next((x for x in index if str(x.get("name", "")) == name), None)
        if not matched:
            return {"ok": False, "error": "plugin_not_found"}
        source_dir = str(matched.get("source_dir", "") or "").strip()
        if not source_dir:
            return {"ok": False, "error": "source_dir_not_provided"}
        src = Path(source_dir)
        if not src.exists():
            return {"ok": False, "error": "source_dir_missing"}
        expected_hash = str(matched.get("source_hash", "") or "").strip().lower()
        if self._plugin_hash_required and not expected_hash:
            return {"ok": False, "error": "source_hash_required"}
        if expected_hash:
            actual_hash = self._hash_directory(src)
            if actual_hash != expected_hash:
                return {"ok": False, "error": "source_hash_mismatch", "expected": expected_hash, "actual": actual_hash}
        dest = self._third_party_dir / name
        if not self._is_within(self._third_party_dir, dest):
            return {"ok": False, "error": "unsafe_plugin_path"}
        version = str(matched.get("version", "") or f"snapshot-{int(time.time())}")
        snap_dir = self._versions_dir / name / version
        if snap_dir.exists():
            shutil.rmtree(snap_dir)
        snap_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, snap_dir)
        if dest.exists():
            backup = self._versions_dir / name / f"backup-{int(time.time() * 1000)}"
            shutil.copytree(dest, backup)
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        self._record_installed(
            {
                "name": name,
                "version": version,
                "compatibility": str(matched.get("compatibility", "")),
                "source_hash": expected_hash,
                "installed_at": time.time(),
                "status": "installed",
                "path": str(dest.resolve()),
            }
        )
        return {"ok": True, "name": name, "path": str(dest.resolve()), "version": version}

    def uninstall(self, plugin_name: str) -> dict[str, Any]:
        name = self._normalize_plugin_name(plugin_name)
        if not name:
            return {"ok": False, "error": "plugin_name_required"}
        dest = self._third_party_dir / name
        if not dest.exists():
            return {"ok": False, "error": "plugin_not_installed"}
        backup = self._versions_dir / name / f"uninstall-{int(time.time() * 1000)}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dest, backup)
        shutil.rmtree(dest)
        self._record_installed({"name": name, "status": "uninstalled", "updated_at": time.time()})
        return {"ok": True, "name": name}

    def set_enabled(self, plugin_name: str, enabled: bool) -> dict[str, Any]:
        name = self._normalize_plugin_name(plugin_name)
        if not name:
            return {"ok": False, "error": "plugin_name_required"}
        yml = self._third_party_dir / name / "plugin.yaml"
        if not yml.exists():
            return {"ok": False, "error": "plugin_not_installed"}
        text = yml.read_text(encoding="utf-8")
        lines = text.splitlines()
        found = False
        out_lines: list[str] = []
        for line in lines:
            if line.strip().startswith("enabled:"):
                out_lines.append(f"enabled: {'true' if enabled else 'false'}")
                found = True
            else:
                out_lines.append(line)
        if not found:
            out_lines.append(f"enabled: {'true' if enabled else 'false'}")
        yml.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        self._record_installed({"name": name, "status": "installed", "enabled": bool(enabled), "updated_at": time.time()})
        return {"ok": True, "name": name, "enabled": bool(enabled)}

    def list_versions(self, plugin_name: str) -> list[dict[str, Any]]:
        name = self._normalize_plugin_name(plugin_name)
        if not name:
            return []
        root = self._versions_dir / name
        if not root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            rows.append({"name": name, "version": d.name, "path": str(d.resolve())})
        return rows

    def rollback(self, plugin_name: str, version: str = "") -> dict[str, Any]:
        name = self._normalize_plugin_name(plugin_name)
        if not name:
            return {"ok": False, "error": "plugin_name_required"}
        versions = self.list_versions(name)
        if not versions:
            return {"ok": False, "error": "no_versions"}
        chosen = None
        if version:
            chosen = next((x for x in versions if str(x.get("version", "")) == str(version)), None)
            if not chosen:
                return {"ok": False, "error": "version_not_found"}
        else:
            chosen = versions[-1]
        src = Path(str(chosen.get("path", "")))
        if not src.exists():
            return {"ok": False, "error": "version_path_missing"}
        dest = self._third_party_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        self._record_installed({"name": name, "status": "installed", "version": chosen.get("version", ""), "updated_at": time.time()})
        return {"ok": True, "name": name, "version": chosen.get("version", "")}

    def _load_index(self) -> list[dict[str, Any]]:
        if self._index_url:
            remote = self._fetch_remote_index(self._index_url)
            if remote is not None:
                self._write_json_file(self._index_file, {"plugins": remote, "fetched_at": time.time(), "source": self._index_url})
                return self._annotate_compatibility(remote)
        local = self._read_json_file(self._index_file)
        plugins = local.get("plugins", []) if isinstance(local, dict) else []
        if not isinstance(plugins, list):
            plugins = []
        return self._annotate_compatibility(plugins)

    def _annotate_compatibility(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            p = dict(item)
            compat = str(p.get("compatibility", "") or "").strip()
            p["compatible"] = self._is_compatible(compat)
            out.append(p)
        out.sort(key=lambda x: str(x.get("name", "")))
        return out

    def _is_compatible(self, compat: str) -> bool:
        if not compat:
            return True
        # Minimal compatibility support: ">=0.1.0", "==0.1.0", "0.1.x"
        cur = gtos_version
        c = compat.strip()
        if c.startswith(">="):
            return cur >= c[2:].strip()
        if c.startswith("=="):
            return cur == c[2:].strip()
        if c.endswith(".x"):
            return cur.startswith(c[:-2])
        return cur == c

    def _fetch_remote_index(self, url: str) -> list[dict[str, Any]] | None:
        self._last_error = ""
        if not self._is_allowed_index_url(url):
            self._last_error = "index_domain_not_allowed"
            return None
        try:
            req = request.Request(url, method="GET")
            with request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                if self._index_sha256:
                    digest = hashlib.sha256(raw).hexdigest().lower()
                    if digest != self._index_sha256:
                        self._last_error = "index_sha256_mismatch"
                        return None
                payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._last_error = "index_fetch_failed"
            return None
        if isinstance(payload, dict):
            rows = payload.get("plugins", [])
            return rows if isinstance(rows, list) else []
        if isinstance(payload, list):
            return payload
        return None

    def _record_installed(self, row: dict[str, Any]) -> None:
        data = self._read_json_file(self._installed_file)
        if not isinstance(data, dict):
            data = {}
        rows = data.get("installed", [])
        if not isinstance(rows, list):
            rows = []
        name = str(row.get("name", ""))
        rows = [r for r in rows if not (isinstance(r, dict) and str(r.get("name", "")) == name)]
        prev = next((r for r in data.get("installed", []) if isinstance(r, dict) and str(r.get("name", "")) == name), {})
        merged = dict(prev if isinstance(prev, dict) else {})
        merged.update(row)
        rows.append(merged)
        data["installed"] = rows
        data["updated_at"] = time.time()
        self._write_json_file(self._installed_file, data)

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
                return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _write_json_file(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(path)

    def _is_allowed_index_url(self, url: str) -> bool:
        if not self._allowed_index_domains:
            return True
        try:
            host = (parse.urlparse(url).hostname or "").lower()
        except Exception:
            return False
        return host in self._allowed_index_domains

    def _hash_directory(self, path: Path) -> str:
        h = hashlib.sha256()
        for f in sorted(path.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(path)).replace("\\", "/")
            h.update(rel.encode("utf-8"))
            with open(f, "rb") as fd:
                while True:
                    chunk = fd.read(1024 * 128)
                    if not chunk:
                        break
                    h.update(chunk)
        return h.hexdigest().lower()

    def _normalize_plugin_name(self, name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            return ""
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
        if any(ch not in allowed for ch in raw):
            return ""
        return raw

    def _is_within(self, root: Path, target: Path) -> bool:
        try:
            target.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False
