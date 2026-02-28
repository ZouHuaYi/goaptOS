"""Adaptive decision engine for plugin and execution strategy selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gtos.adaptive_engine.capability_registry import CapabilityRegistry
from gtos.adaptive_engine.scoring_model import CapabilityScoringModel


@dataclass(slots=True)
class TaskProfile:
    complexity_score: float
    estimated_code_size: int
    risk_level: str
    domain_type: str
    requires_parallel: bool
    requires_external_tool: bool
    time_sensitive: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveDecisionEngine:
    def __init__(self, registry: CapabilityRegistry, scoring: CapabilityScoringModel | None = None) -> None:
        self._registry = registry
        self._scoring = scoring or CapabilityScoringModel()

    def build_task_profile(self, task_prompt: str, assessment: dict[str, Any] | None = None) -> TaskProfile:
        text = (task_prompt or "").lower()
        complexity_score = min(1.0, max(0.05, len(task_prompt or "") / 240.0))
        estimated_code_size = max(30, min(2000, int(len(task_prompt or "") * 1.5)))
        risk_level = str((assessment or {}).get("risk_level", "low"))
        if any(k in text for k in ["delete", "drop table", "shutdown", "production", "kill process"]):
            risk_level = "high" if risk_level != "blocked" else risk_level
        domain_type = "python" if "python" in text else "general"
        requires_parallel = complexity_score >= 0.55 or any(k in text for k in ["并行", "parallel", "batch", "multi"])
        requires_external_tool = any(k in text for k in ["browser", "chrome", "git", "shell", "api", "网络", "网页"])
        time_sensitive = any(k in text for k in ["快速", "asap", "urgent", "实时", "立刻"])
        return TaskProfile(
            complexity_score=round(complexity_score, 4),
            estimated_code_size=estimated_code_size,
            risk_level=risk_level,
            domain_type=domain_type,
            requires_parallel=requires_parallel,
            requires_external_tool=requires_external_tool,
            time_sensitive=time_sensitive,
        )

    def decide(
        self,
        task_prompt: str,
        assessment: dict[str, Any],
        enabled_plugins: list[str],
        exec_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        profile = self.build_task_profile(task_prompt, assessment=assessment)
        capability_names = list(dict.fromkeys((enabled_plugins or []) + ["planner", "single_task", "parallel_dag"]))
        self._registry.ensure(capability_names)

        score_map: dict[str, float] = {}
        for name in capability_names:
            score_map[name] = self._scoring.score(self._registry.get(name), profile.to_dict())

        selected_plugins = sorted(enabled_plugins or [], key=lambda n: score_map.get(n, 0.0), reverse=True)
        top_n = 3 if profile.complexity_score < 0.45 else len(selected_plugins)
        selected_plugins = selected_plugins[: max(2, min(len(selected_plugins), top_n))]
        if "logger" in (enabled_plugins or []) and "logger" not in selected_plugins:
            selected_plugins = ["logger"] + selected_plugins
        if "feedback" in (enabled_plugins or []) and "feedback" not in selected_plugins:
            selected_plugins.append("feedback")

        planner_score = score_map.get("planner", 0.0)
        single_score = score_map.get("single_task", 0.0)
        use_planner = bool(exec_cfg.get("use_planner", False))
        if profile.complexity_score >= 0.55:
            use_planner = planner_score >= (single_score - 0.05)
        elif profile.complexity_score < 0.35:
            use_planner = planner_score > (single_score + 0.18) and profile.risk_level in {"medium", "high"}

        dag_parallel = bool(exec_cfg.get("dag_parallel", False))
        if use_planner:
            parallel_score = score_map.get("parallel_dag", 0.0)
            dag_parallel = profile.requires_parallel and parallel_score > 0.2 and profile.risk_level in {"low", "medium"}
            if profile.risk_level in {"high", "blocked"}:
                dag_parallel = False

        overrides = {
            "use_planner": use_planner,
            "dag_parallel": dag_parallel,
            "dag_max_workers": int(exec_cfg.get("dag_max_workers", 4)),
            "node_retry_count": int(exec_cfg.get("node_retry_count", 0)),
            "dag_fail_policy": str(exec_cfg.get("dag_fail_policy", "skip")),
        }
        if profile.risk_level in {"high", "blocked"}:
            overrides["dag_max_workers"] = 1
            overrides["node_retry_count"] = max(overrides["node_retry_count"], 1)
            overrides["dag_fail_policy"] = "stop"

        return {
            "task_profile": profile.to_dict(),
            "scores": score_map,
            "selected_plugins": selected_plugins,
            "execution_overrides": overrides,
        }
