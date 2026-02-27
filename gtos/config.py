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
            "node_retry_count": 0,
            "dag_fail_policy": "skip",
        },
        "plugins": {
            "enabled": ["logger", "feedback", "skill", "agent", "llm_optimizer"],
            "skill": {
                "recent_count": 3,
                "retrieval_top_k": 5,
                "min_relevance": 0.22,
                "max_context_chars": 900,
                "ab_test": {
                    "mode": "auto",
                    "treatment_ratio": 0.5,
                    "salt": "skill-ab-v1",
                    "metrics_file": str(data_dir / "skill_ab_metrics.json"),
                },
            },
            "llm_optimizer": {"refine": False},
        },
        "analytics": {
            "runs_file": str(data_dir / "runs.jsonl"),
            "metrics_file": str(data_dir / "metrics.json"),
        },
        "optimization": {
            "enabled": True,
            "mode": "suggest",
            "runs_file": str(data_dir / "runs.jsonl"),
            "output_file": str(data_dir / "strategy_state.json"),
            "window": 80,
            "target_success_rate": 0.85,
            "target_avg_fix_rounds": 0.8,
            "target_avg_latency_ms": 8000,
        },
        "self_cognition": {
            "mode": "advise",
            "profile_file": str(data_dir / "cognition_profile.json"),
            "allowed_domains": ["python", "automation", "code_generation", "debug"],
            "blocked_keywords": ["rm -rf", "format disk", "wipe", "ransomware"],
            "high_risk_keywords": ["delete", "drop table", "shutdown", "kill process", "production"],
            "dynamic": {
                "enabled": True,
                "runs_file": str(data_dir / "runs.jsonl"),
                "window": 200,
                "min_samples": 8,
                "fail_rate_warn": 0.35,
                "fail_rate_reject": 0.7,
                "avg_fix_rounds_warn": 1.2,
            },
        },
        "visualization": {
            "enabled": True,
            "runs_file": str(data_dir / "runs.jsonl"),
            "ab_metrics_file": str(data_dir / "skill_ab_metrics.json"),
            "json_file": str(data_dir / "dashboard.json"),
            "markdown_file": str(data_dir / "dashboard.md"),
            "window": 100,
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
    """将 paths/analytics/optimization/self_cognition/visualization 下相对路径解析为基于 root 的绝对路径。"""
    out = dict(cfg)
    paths = out.get("paths", {})
    resolved = {}
    for k, v in paths.items():
        if isinstance(v, str) and v and not Path(v).is_absolute():
            resolved[k] = str((root / v).resolve())
        else:
            resolved[k] = v
    out["paths"] = resolved
    analytics = out.get("analytics", {})
    analytics_resolved = {}
    for k, v in analytics.items():
        if isinstance(v, str) and v and not Path(v).is_absolute():
            analytics_resolved[k] = str((root / v).resolve())
        else:
            analytics_resolved[k] = v
    out["analytics"] = analytics_resolved
    optimization = out.get("optimization", {})
    optimization_resolved = dict(optimization)
    for k in ("runs_file", "output_file"):
        v = optimization_resolved.get(k)
        if isinstance(v, str) and v and not Path(v).is_absolute():
            optimization_resolved[k] = str((root / v).resolve())
    out["optimization"] = optimization_resolved
    sc = out.get("self_cognition", {})
    if isinstance(sc.get("profile_file"), str) and sc.get("profile_file") and not Path(sc["profile_file"]).is_absolute():
        sc["profile_file"] = str((root / sc["profile_file"]).resolve())
    dynamic = sc.get("dynamic", {}) if isinstance(sc.get("dynamic"), dict) else {}
    if isinstance(dynamic.get("runs_file"), str) and dynamic.get("runs_file") and not Path(dynamic["runs_file"]).is_absolute():
        dynamic["runs_file"] = str((root / dynamic["runs_file"]).resolve())
    sc["dynamic"] = dynamic
    out["self_cognition"] = sc
    vis = out.get("visualization", {})
    vis_resolved = dict(vis)
    for k in ("runs_file", "ab_metrics_file", "json_file", "markdown_file"):
        v = vis_resolved.get(k)
        if isinstance(v, str) and v and not Path(v).is_absolute():
            vis_resolved[k] = str((root / v).resolve())
    out["visualization"] = vis_resolved
    return out


def get_data_dir(config: dict[str, Any]) -> Path:
    """从配置推导 data 目录，用于相对路径。"""
    skills = config.get("paths", {}).get("skills_file", "")
    if skills:
        return Path(skills).resolve().parent
    return Path(__file__).resolve().parents[1] / "data"
