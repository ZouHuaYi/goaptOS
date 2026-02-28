import time
from pathlib import Path

from gtos.analytics.prompt_auto_optimizer import PromptAutoOptimizer
from gtos.metrics.collector import MetricsCollector


def test_metrics_collector_records_and_summarizes() -> None:
    ts = int(time.time() * 1000)
    metrics_file = Path(f"data/_unit_prompt_metrics_{ts}.jsonl")
    collector = MetricsCollector(metrics_file)
    collector.record_run("task a", {"success": False, "fix_rounds": 2, "_metrics": {"latency_ms": 1200.0}, "error": "boom"})
    collector.record_run("task b", {"success": True, "fix_rounds": 0, "_metrics": {"latency_ms": 300.0}, "stdout": "ok"})
    summary = collector.summarize(window=10)
    assert summary["samples"] == 2
    assert summary["failure_rate"] > 0
    assert summary["avg_fix_rounds"] >= 1.0
    assert summary["avg_token_total"] > 0


def test_prompt_auto_optimizer_applies_on_thresholds() -> None:
    ts = int(time.time() * 1000)
    state_file = Path(f"data/_unit_prompt_state_{ts}.json")
    optimizer = PromptAutoOptimizer(
        {
            "enabled": True,
            "window": 10,
            "min_samples": 3,
            "failure_rate_threshold": 0.3,
            "avg_fix_rounds_threshold": 1.0,
            "avg_token_threshold": 500,
            "state_file": str(state_file),
        }
    )
    metrics = {
        "samples": 5,
        "failure_rate": 0.6,
        "avg_fix_rounds": 1.8,
        "avg_token_total": 900,
    }
    out = optimizer.optimize(metrics, current_profiles={})
    assert out["enabled"] is True
    assert out["applied"] is True
    profiles = out.get("profiles", {})
    assert "generate_code" in profiles
    assert "fix_code" in profiles
    assert "react_step" in profiles
    assert state_file.exists()

