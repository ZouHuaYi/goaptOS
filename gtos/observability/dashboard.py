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
        self._skills_file = Path(cfg.get("skills_file", "data/skills.json"))
        self._skill_drafts_file = Path(cfg.get("skill_drafts_file", "data/skill_drafts.json"))

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
            "skill_lifecycle": self._load_skill_lifecycle(),
            "skill_drafts": self._load_skill_drafts(),
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
        if result.get("execution_state"):
            out["execution_state"] = result.get("execution_state")
        if result.get("_error"):
            out["error"] = result.get("_error")
        if result.get("checkpoint_file"):
            out["checkpoint_file"] = result.get("checkpoint_file")
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
        sl = payload.get("skill_lifecycle", {})
        sd = payload.get("skill_drafts", {})
        lines = [
            "# God View Dashboard",
            "",
            f"- Success rate: {round(float(s.get('success_rate', 0.0)) * 100, 2)}%",
            f"- Avg latency (ms): {s.get('avg_latency_ms', 0)}",
            f"- Avg fix rounds: {s.get('avg_fix_rounds', 0)}",
            f"- Failed runs: {s.get('failed', 0)} / {s.get('window', 0)}",
            f"- Skills total/active/expired: {sl.get('total', 0)} / {sl.get('active', 0)} / {sl.get('expired', 0)}",
            f"- Skills avg score: {sl.get('avg_score', 0.0)}",
            f"- Skill drafts (proposed): {sd.get('proposed', 0)}",
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

    def _load_skill_lifecycle(self) -> dict[str, Any]:
        items = self._read_json_list(self._skills_file)
        if not items:
            return {
                "total": 0,
                "active": 0,
                "expired": 0,
                "avg_score": 0.0,
                "score_buckets": {"0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0},
                "version_distribution": [],
                "recent_score_trend": [],
                "top_skills": [],
            }
        total = len(items)
        active = sum(1 for x in items if not bool((x or {}).get("expired", False)))
        expired = total - active
        scores = [float((x or {}).get("score", 0.0) or 0.0) for x in items]
        avg_score = round(sum(scores) / total, 4) if total else 0.0

        buckets = {"0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for s in scores:
            if s < 0.3:
                buckets["0-0.3"] += 1
            elif s < 0.6:
                buckets["0.3-0.6"] += 1
            elif s < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1

        task_versions: dict[str, int] = {}
        for x in items:
            key = str((x or {}).get("task_key", "") or (x or {}).get("task", ""))[:100]
            v = int((x or {}).get("version", 1) or 1)
            task_versions[key] = max(task_versions.get(key, 0), v)
        version_distribution = [
            {"task_key": k, "max_version": v} for k, v in sorted(task_versions.items(), key=lambda kv: -kv[1])[:20]
        ]

        recent = sorted(items, key=lambda x: float((x or {}).get("last_used_at", (x or {}).get("created_at", 0.0)) or 0.0))[-30:]
        recent_score_trend = [
            {"ts": float((x or {}).get("last_used_at", (x or {}).get("created_at", 0.0)) or 0.0), "score": float((x or {}).get("score", 0.0) or 0.0)}
            for x in recent
        ]

        top_skills = sorted(items, key=lambda x: float((x or {}).get("score", 0.0) or 0.0), reverse=True)[:10]
        return {
            "total": total,
            "active": active,
            "expired": expired,
            "avg_score": avg_score,
            "score_buckets": buckets,
            "version_distribution": version_distribution,
            "recent_score_trend": recent_score_trend,
            "top_skills": [
                {
                    "skill_id": x.get("skill_id"),
                    "task": str(x.get("task", ""))[:120],
                    "score": float(x.get("score", 0.0) or 0.0),
                    "version": int(x.get("version", 1) or 1),
                    "status": x.get("status", "active"),
                }
                for x in top_skills
            ],
        }

    def _load_skill_drafts(self) -> dict[str, Any]:
        items = self._read_json_list(self._skill_drafts_file)
        recent = [x for x in items if isinstance(x, dict)][-20:]
        accepted = [x for x in items if str((x or {}).get("status", "")) == "accepted"]
        uplifts = [float(((x or {}).get("acceptance", {}) or {}).get("score_uplift", 0.0) or 0.0) for x in accepted]
        return {
            "total": len(items),
            "proposed": sum(1 for x in items if str((x or {}).get("status", "")) == "proposed"),
            "accepted": sum(1 for x in items if str((x or {}).get("status", "")) == "accepted"),
            "rejected": sum(1 for x in items if str((x or {}).get("status", "")) == "rejected"),
            "acceptance_rate": round((len(accepted) / len(items)), 4) if items else 0.0,
            "avg_score_uplift": round((sum(uplifts) / len(uplifts)), 4) if uplifts else 0.0,
            "recent": recent,
        }

    def _read_json_list(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
                if isinstance(obj, list):
                    return [x for x in obj if isinstance(x, dict)]
        except Exception:
            return []
        return []
