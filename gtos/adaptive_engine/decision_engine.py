"""Adaptive decision engine for plugin and execution strategy selection."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from gtos.adaptive_engine.bandit import TaskBucketBandit
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
    def __init__(
        self,
        registry: CapabilityRegistry,
        scoring: CapabilityScoringModel | None = None,
        bandit: TaskBucketBandit | None = None,
    ) -> None:
        self._registry = registry
        self._scoring = scoring or CapabilityScoringModel()
        self._bandit = bandit

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

        bucket = self._bucket_name(profile)
        combo_candidates = self._build_combo_candidates(enabled_plugins or [], profile=profile, score_map=score_map)
        combo_arm_names = [c["arm_name"] for c in combo_candidates]
        strategy_arm = "single_task"
        bandit_scores: dict[str, float] = {}
        bandit_selected_algo = "none"
        bandit_shadow_arm = ""
        bandit_shadow_algo = ""
        bandit_shadow_scores: dict[str, float] = {}
        if self._bandit is None:
            chosen_combo = combo_candidates[0] if combo_candidates else {"plugins": list(enabled_plugins or []), "strategy": "single_task", "arm_name": "single_task|default"}
        else:
            pick = self._bandit.select(bucket=bucket, available_arms=combo_arm_names, context_key=task_prompt)
            picked_name = str(pick.get("selected_arm", "") or "")
            chosen_combo = next((x for x in combo_candidates if x["arm_name"] == picked_name), combo_candidates[0])
            bandit_scores = pick.get("scores", {}) if isinstance(pick.get("scores"), dict) else {}
            bandit_selected_algo = str(pick.get("selected_algo", "ucb"))
            bandit_shadow_arm = str(pick.get("shadow_arm", ""))
            bandit_shadow_algo = str(pick.get("shadow_algo", ""))
            bandit_shadow_scores = pick.get("shadow_scores", {}) if isinstance(pick.get("shadow_scores"), dict) else {}

        selected_plugins = list(chosen_combo.get("plugins", []))
        strategy_arm = str(chosen_combo.get("strategy", "single_task"))
        use_planner, dag_parallel = self._arm_to_strategy(strategy_arm, profile, exec_cfg)
        multi_agent_enabled = self._should_enable_multi_agent(
            profile=profile,
            strategy_arm=strategy_arm,
            enabled_plugins=enabled_plugins or [],
        )
        multi_agent_max_rounds = 3 if profile.complexity_score >= 0.75 else 2

        overrides = {
            "use_planner": use_planner,
            "dag_parallel": dag_parallel,
            "dag_max_workers": int(exec_cfg.get("dag_max_workers", 4)),
            "node_retry_count": int(exec_cfg.get("node_retry_count", 0)),
            "dag_fail_policy": str(exec_cfg.get("dag_fail_policy", "skip")),
            "multi_agent_enabled": multi_agent_enabled,
            "multi_agent_mode": "planner_executor_reviewer",
            "multi_agent_max_rounds": multi_agent_max_rounds,
        }
        if profile.risk_level in {"high", "blocked"}:
            overrides["dag_max_workers"] = 1
            overrides["node_retry_count"] = max(overrides["node_retry_count"], 1)
            overrides["dag_fail_policy"] = "stop"
            overrides["multi_agent_enabled"] = False

        return {
            "task_profile": profile.to_dict(),
            "scores": score_map,
            "selected_plugins": selected_plugins,
            "execution_overrides": overrides,
            "bandit": {
                "bucket": bucket,
                "selected_arm": strategy_arm,
                "selected_combo_arm": chosen_combo.get("arm_name"),
                "selected_plugins": selected_plugins,
                "selected_algo": bandit_selected_algo,
                "scores": {k: (9999.0 if not math.isfinite(v) else round(v, 6)) for k, v in bandit_scores.items()},
                "shadow_arm": bandit_shadow_arm,
                "shadow_algo": bandit_shadow_algo,
                "shadow_scores": {k: (9999.0 if not math.isfinite(v) else round(v, 6)) for k, v in bandit_shadow_scores.items()},
            },
        }

    def _select_strategy_arm(self, profile: TaskProfile, score_map: dict[str, float], bucket: str) -> tuple[str, dict[str, float]]:
        candidate_arms = ["single_task", "planner_serial", "planner_parallel"]
        if profile.risk_level in {"high", "blocked"}:
            candidate_arms = ["single_task", "planner_serial"]
        if self._bandit is None:
            s_single = score_map.get("single_task", 0.0)
            s_plan = score_map.get("planner", 0.0)
            s_parallel = score_map.get("parallel_dag", 0.0)
            if profile.requires_parallel and s_parallel >= max(s_single, s_plan):
                return "planner_parallel", {"planner_parallel": s_parallel}
            if s_plan >= s_single:
                return "planner_serial", {"planner_serial": s_plan}
            return "single_task", {"single_task": s_single}
        return self._bandit.select(bucket=bucket, available_arms=candidate_arms)

    def _build_combo_candidates(self, enabled_plugins: list[str], profile: TaskProfile, score_map: dict[str, float]) -> list[dict[str, Any]]:
        ranked = sorted(enabled_plugins or [], key=lambda n: score_map.get(n, 0.0), reverse=True)
        core = [x for x in ["logger", "feedback", "skill"] if x in ranked]
        with_agent = core + (["agent"] if "agent" in ranked else [])
        with_opt = core + (["llm_optimizer"] if "llm_optimizer" in ranked else [])
        full = list(dict.fromkeys(ranked))
        combos = [core or ranked[:2], with_agent or ranked[:3], with_opt or ranked[:3], full]
        dedup: list[list[str]] = []
        for c in combos:
            uniq = list(dict.fromkeys([x for x in c if x]))
            if uniq and uniq not in dedup:
                dedup.append(uniq)
        strategies = ["single_task", "planner_serial", "planner_parallel"]
        if profile.risk_level in {"high", "blocked"}:
            strategies = ["single_task", "planner_serial"]
        out: list[dict[str, Any]] = []
        for s in strategies:
            for plugins in dedup:
                pid = "+".join(plugins)
                out.append({"strategy": s, "plugins": plugins, "arm_name": f"{s}|{pid}"})
        return out or [{"strategy": "single_task", "plugins": ranked[:2], "arm_name": "single_task|default"}]

    def _arm_to_strategy(self, arm: str, profile: TaskProfile, exec_cfg: dict[str, Any]) -> tuple[bool, bool]:
        # External-tool tasks benefit from ReAct single-task flow to allow runtime tool calls.
        if profile.requires_external_tool and profile.risk_level not in {"high", "blocked"}:
            return False, False
        if arm == "single_task":
            return False, False
        if arm == "planner_parallel":
            if profile.risk_level in {"high", "blocked"}:
                return True, False
            return True, True
        return True, False

    def _should_enable_multi_agent(self, profile: TaskProfile, strategy_arm: str, enabled_plugins: list[str]) -> bool:
        if "agent" not in enabled_plugins:
            return False
        if profile.risk_level in {"high", "blocked"}:
            return False
        if profile.requires_external_tool:
            return True
        if strategy_arm != "single_task":
            return False
        if profile.requires_parallel or profile.time_sensitive:
            return True
        return profile.complexity_score >= 0.55

    def _bucket_name(self, profile: TaskProfile) -> str:
        c = "simple" if profile.complexity_score < 0.35 else ("complex" if profile.complexity_score >= 0.6 else "medium")
        r = profile.risk_level.lower()
        d = profile.domain_type
        return f"{c}:{r}:{d}"
