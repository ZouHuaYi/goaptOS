# Plugin Market (Sprint 4.3)

GTOS supports a plugin market index for third-party plugins.

## Config

```json
{
  "plugins": {
    "third_party": {
      "enabled": true,
      "dir": "plugins/third_party",
      "market": {
        "index_url": "",
        "index_file": "data/plugin_market_index.json",
        "installed_file": "data/plugin_market_installed.json",
        "security": {
          "allowed_index_domains": ["raw.githubusercontent.com"],
          "index_sha256": "",
          "plugin_hash_required": false
        }
      }
    }
  }
}
```

## Index schema

`plugins` list supports:
- `name`
- `version`
- `compatibility` (e.g. `>=0.1.0`, `==0.1.0`, `0.1.x`)
- `description`
- `source_dir` (local folder path, install source)
- `source_hash` (optional sha256 over source directory for integrity check)

## Web API

- `GET /api/plugins/market` returns index + installed plugins + compatibility
- `POST /api/plugins/install` with `{ "name": "plugin_name" }`
- `POST /api/plugins/uninstall` with `{ "name": "plugin_name" }`
- `POST /api/plugins/toggle` with `{ "name": "plugin_name", "enabled": true|false }`
- `POST /api/plugins/rollback` with `{ "name": "plugin_name", "version": "optional" }`
- `GET /api/plugins/versions?name=plugin_name`
- `POST /api/plugins/reload` hot-reload check (plugins are re-scanned per run)
- `GET /api/runtime/status` returns runtime flags and plugin settings
