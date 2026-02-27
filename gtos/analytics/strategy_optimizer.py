"""Auto strategy tuning based on recent run metrics."""

import json
from pathlib import Path
from typing import Any

from gtos.analytics.feedback_analyzer import FeedbackAnalyzer


class StrategyOptimizer:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._mode = str(cfg.get("mode", "suggest")).strip().lower()  # suggest | apply
        self._window = int(cfg.get("window", 80))
        self._runs_file = str(cfg.get("runs_file", "data/runs.jsonl"))
        self._output_file = Path(cfg.get("output_file", "data/strategy_state.json"))
        self._threshold_success = float(cfg.get("target_success_rate", 0.85))
        self._threshold_fix = float(cfg.get("target_avg_fix_rounds", 0.8))
        self._threshold_latency_ms = float(cfg.get("target_avg_latency_ms", 8000))

    def optimize(self, current_config: dict[str, Any]) -> dict[str, Any]:
        if not self._enabled:
            return {"enabled": False, "mode": self._mode, "applied": False, "proposed": {}}

        analyzer = FeedbackAnalyzer(self._runs_file)
        metrics = analyzer.summarize(limit=self._window)
        proposed = self._propose(current=current_config, metrics=metrics)
        applied = self._mode == "apply"

        if applied:
            self._apply_to_config(current_config, proposed)

        state = {
            "enabled": True,
            "mode": self._mode,
            "applied": applied,
            "metrics_window": metrics,
            "proposed": proposed,
        }
        self._persist_state(state)
        return state

    def _propose(self, current: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        executor = current.setdefault("executor", {})
        plugins = current.setdefault("plugins", {})
        llm_opt = plugins.setdefault("llm_optimizer", {})
        proposed: dict[str, Any] = {
            "executor": {
                "dag_parallel": bool(executor.get("dag_parallel", False)),
                "dag_max_workers": int(executor.get("dag_max_workers", 4)),
                "node_retry_count": int(executor.get("node_retry_count", 0)),
                "dag_fail_policy": str(executor.get("dag_fail_policy", "skip")),
            },
            "plugins": {
                "llm_optimizer": {"refine": bool(llm_opt.get("refine", False))}
            },
        }

        success_rate = float(metrics.get("success_rate", 0.0))
        avg_fix = float(metrics.get("avg_fix_rounds", 0.0))
        avg_latency = float(metrics.get("avg_latency_ms", 0.0))

        if success_rate < self._threshold_success:
            proposed["executor"]["node_retry_count"] = max(proposed["executor"]["node_retry_count"], 1)
            proposed["executor"]["dag_fail_policy"] = "stop"
            proposed["plugins"]["llm_optimizer"]["refine"] = True
        if avg_fix > self._threshold_fix:
            proposed["executor"]["node_retry_count"] = max(proposed["executor"]["node_retry_count"], 2)
            proposed["plugins"]["llm_optimizer"]["refine"] = True
        if avg_latency > self._threshold_latency_ms:
            proposed["executor"]["dag_parallel"] = False
            proposed["executor"]["dag_max_workers"] = 1
        if success_rate >= self._threshold_success and avg_fix <= self._threshold_fix and avg_latency <= self._threshold_latency_ms:
            proposed["executor"]["dag_fail_policy"] = "skip"
            proposed["executor"]["node_retry_count"] = min(proposed["executor"]["node_retry_count"], 1)

        return proposed

    def _apply_to_config(self, cfg: dict[str, Any], proposed: dict[str, Any]) -> None:
        ex = cfg.setdefault("executor", {})
        ex.update(proposed.get("executor", {}))
        plugins = cfg.setdefault("plugins", {})
        llm_opt = plugins.setdefault("llm_optimizer", {})
        llm_opt.update((proposed.get("plugins", {}) or {}).get("llm_optimizer", {}))

    def _persist_state(self, state: dict[str, Any]) -> None:
        self._output_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._output_file.with_suffix(self._output_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp.replace(self._output_file)
