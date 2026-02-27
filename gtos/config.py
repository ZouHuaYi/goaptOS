# gtos/config.py
"""配置加载：从 config.json 或环境变量 GTOS_CONFIG 指定路径加载，缺失项用默认值。"""

import json
import os
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    """项目根目录：以 config 文件所在或 cwd 为准。"""
    for p in [Path.cwd(), Path(__file__).resolve().parents[1]]:
        if (p / "config.json").exists():
            return p
    return Path.cwd()


def _default_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    return {
        "paths": {
            "skills_file": str(data_dir / "skills.json"),
            "sqlite_db": str(data_dir / "gtos.db"),
        },
        "executor": {
            "max_fix_rounds": 3,
            "timeout_seconds": 30,
            "use_planner": False,
            "dag_parallel": False,
            "dag_max_workers": 4,
        },
        "plugins": {
            "enabled": ["logger", "skill", "agent", "llm_optimizer"],
            "skill": {"recent_count": 3, "retrieval_top_k": 5},
            "llm_optimizer": {"refine": False},
        },
        "memory": {
            "vector_store": {
                "enabled": True,
                "backend": "keyword",
                "persist_path": "",
                "embedding": {
                    "enabled": False,
                    "provider": "openai_compatible",
                    "base_url": "",
                    "model": "text-embedding-3-small",
                    "api_key_env": "OPENAI_API_KEY",
                    "api_key": "",
                    "timeout_seconds": 60,
                },
            },
        },
        "logging": {"level": "INFO"},
        "default_task": "用 Python 打印 Hello from gtos 并计算 1+2",
        "llm": {
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "tokenizer_model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
            "api_key": "",
            "temperature": 0.2,
            "max_output_tokens": 1200,
            "max_input_tokens": 12000,
            "timeout_seconds": 60,
        },
    }


def _deep_merge(default: dict, override: dict) -> dict:
    out = dict(default)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """加载配置。优先级：参数路径 > 环境变量 GTOS_CONFIG > 项目根 config.json > 默认。"""
    path = None
    if config_path:
        path = Path(config_path)
    elif os.environ.get("GTOS_CONFIG"):
        path = Path(os.environ["GTOS_CONFIG"])
    else:
        root = _project_root()
        path = root / "config.json"
    default = _default_config()
    root = path.parent if path else Path.cwd()
    if not path or not path.exists():
        return _resolve_paths(default, root)
    with open(path, "r", encoding="utf-8") as f:
        user = json.load(f)
    merged = _deep_merge(default, user)
    return _resolve_paths(merged, root)


def _resolve_paths(cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    """将 paths 下相对路径解析为基于 root 的绝对路径。"""
    out = dict(cfg)
    paths = out.get("paths", {})
    resolved = {}
    for k, v in paths.items():
        if isinstance(v, str) and v and not Path(v).is_absolute():
            resolved[k] = str((root / v).resolve())
        else:
            resolved[k] = v
    out["paths"] = resolved
    return out


def get_data_dir(config: dict[str, Any]) -> Path:
    """从配置推导 data 目录，用于相对路径。"""
    skills = config.get("paths", {}).get("skills_file", "")
    if skills:
        return Path(skills).resolve().parent
    return Path(__file__).resolve().parents[1] / "data"
