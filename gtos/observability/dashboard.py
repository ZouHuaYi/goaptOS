"""Generate a lightweight 'god-view' dashboard snapshot."""

import json
import time
from pathlib import Path
from typing import Any

from gtos.analytics.feedback_analyzer import FeedbackAnalyzer


class GodViewBuilder:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._runs_file = str(cfg.get("runs_file", "data/runs.jsonl"))
        self._ab_metrics_file = Path(cfg.get("ab_metrics_file", "data/skill_ab_metrics.json"))
        self._json_path = Path(cfg.get("json_file", "data/dashboard.json"))
        self._md_path = Path(cfg.get("markdown_file", "data/dashboard.md"))
        self._window = int(cfg.get("window", 100))

    def build(self, *, last_result: dict[str, Any] | None = None, last_assessment: dict[str, Any] | None = None, last_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._enabled:
            return {"enabled": False}
        analyzer = FeedbackAnalyzer(self._runs_file)
        summary = analyzer.summarize(limit=self._window)
        payload = {
            "generated_ts": time.time(),
            "window": self._window,
            "summary": summary,
            "ab_metrics": self._load_ab_metrics(),
            "last_assessment": last_assessment or {},
            "last_policy": last_policy or {},
            "last_result": self._strip_result(last_result or {}),
        }
        self._write_json(payload)
        self._write_markdown(payload)
        return payload

    def _strip_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if not result:
            return {}
        out = {"success": bool(result.get("success"))}
        if result.get("summary"):
            out["summary"] = result.get("summary")
        if result.get("failure_chain"):
            out["failure_chain"] = result.get("failure_chain")
        if result.get("results"):
            out["node_results"] = [
                {
                    "id": r.get("id"),
                    "success": bool(r.get("success")),
                    "skipped": bool(r.get("skipped")),
                    "attempts": (r.get("_node", {}) or {}).get("attempts"),
                    "latency_ms": (r.get("_node", {}) or {}).get("latency_ms"),
                }
                for r in result.get("results", [])
            ]
        return out

    def _write_json(self, payload: dict[str, Any]) -> None:
        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._json_path.with_suffix(self._json_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self._json_path)

    def _load_ab_metrics(self) -> dict[str, Any]:
        if not self._ab_metrics_file.exists():
            return {}
        try:
            with open(self._ab_metrics_file, "r", encoding="utf-8") as f:
                obj = json.load(f)
                return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _write_markdown(self, payload: dict[str, Any]) -> None:
        s = payload.get("summary", {})
        lines = [
            "# God View Dashboard",
            "",
            f"- Success rate: {round(float(s.get('success_rate', 0.0)) * 100, 2)}%",
            f"- Avg latency (ms): {s.get('avg_latency_ms', 0)}",
            f"- Avg fix rounds: {s.get('avg_fix_rounds', 0)}",
            f"- Failed runs: {s.get('failed', 0)} / {s.get('window', 0)}",
            "",
            "## Last Assessment",
            f"- Risk: {(payload.get('last_assessment', {}) or {}).get('risk_level', '')}",
            f"- Capability score: {(payload.get('last_assessment', {}) or {}).get('capability_score', '')}",
            "",
            "## Last Policy",
            f"- Parallel: {(payload.get('last_policy', {}) or {}).get('parallel', '')}",
            f"- Workers: {(payload.get('last_policy', {}) or {}).get('max_workers', '')}",
            f"- Retries: {(payload.get('last_policy', {}) or {}).get('node_retry_count', '')}",
            f"- Fail policy: {(payload.get('last_policy', {}) or {}).get('fail_policy', '')}",
            "",
        ]
        self._md_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._md_path.with_suffix(self._md_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")
        tmp.replace(self._md_path)
