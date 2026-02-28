from pathlib import Path

from gtos.adaptive_engine import AdaptiveDecisionEngine, CapabilityRegistry, CapabilityStatsUpdater, TaskBucketBandit


def test_adaptive_decision_returns_dynamic_plugin_order(tmp_path: Path) -> None:
    stats_file = tmp_path / "capability_stats.json"
    registry = CapabilityRegistry(stats_file=stats_file)
    bandit = TaskBucketBandit(file_path=tmp_path / "bandit.json")
    engine = AdaptiveDecisionEngine(registry=registry, bandit=bandit)
    decision = engine.decide(
        task_prompt="请并行处理多个 python 子任务并输出结果",
        assessment={"risk_level": "low"},
        enabled_plugins=["logger", "feedback", "skill", "agent", "llm_optimizer"],
        exec_cfg={"use_planner": True, "dag_parallel": False, "dag_max_workers": 4, "node_retry_count": 0, "dag_fail_policy": "skip"},
    )
    assert "selected_plugins" in decision
    assert len(decision["selected_plugins"]) >= 2
    assert "execution_overrides" in decision
    assert "task_profile" in decision
    assert "bandit" in decision
    assert "|" in str(decision["bandit"].get("selected_combo_arm", ""))


def test_stats_updater_updates_registry_ema(tmp_path: Path) -> None:
    stats_file = tmp_path / "capability_stats.json"
    registry = CapabilityRegistry(stats_file=stats_file)
    registry.ensure(["skill", "planner"])
    updater = CapabilityStatsUpdater(registry=registry, ema_alpha=0.5)
    updater.update_from_result(
        ["skill", "planner"],
        result={
            "success": True,
            "_metrics": {"latency_ms": 3000},
            "summary": {"retried_nodes": 1},
            "task": "x",
            "code": "print(1)",
            "stdout": "1",
            "stderr": "",
        },
        assessment={"risk_level": "medium"},
    )
    skill = registry.get("skill")
    assert skill.usage_count == 1
    assert skill.success_rate > 0.6
    assert skill.avg_retries >= 0.5
