# Plugin SDK

Third-party plugins are discovered from `plugins/third_party/*/plugin.yaml`.

## plugin.yaml

```yaml
name: sample_plugin
events:
  - on_action
  - on_reflection_complete
class: Plugin
source: plugin.py
enabled: true
```

Supported fields:
- `name`: plugin id
- `events`: declared interested events (metadata, not enforced)
- `class`: class name to instantiate (default `Plugin`)
- `source`: python file relative to manifest directory (default `plugin.py`)
- `module`: importable python module path (optional, higher priority than `source`)
- `class_path`: `module.path:ClassName` shorthand (optional)
- `enabled`: whether this plugin is loadable

## Runtime behavior

- Built-in plugins are still loaded by `plugins.enabled`.
- Third-party plugins are auto-discovered when `plugins.third_party.enabled=true`.
- Discovery directory defaults to `plugins/third_party`.
- Failed plugin parsing/loading is logged as warning and does not stop task execution.

