"""Utilities to summarize run logs and error patterns."""

import json
from pathlib import Path
from typing import Any


class FeedbackAnalyzer:
    def __init__(self, runs_path: str) -> None:
        self._runs_path = Path(runs_path)

    def _read_finishes(self, level: str | None = None) -> list[dict[str, Any]]:
        if not self._runs_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        starts: dict[str, dict[str, Any]] = {}
        with open(self._runs_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if item.get("event") == "run_start":
                    starts[item.get("run_id", "")] = item
                if item.get("event") == "run_finish":
                    rid = item.get("run_id", "")
                    lvl = item.get("level") or ((starts.get(rid, {}) or {}).get("meta", {}) or {}).get("level", "node")
                    item["level"] = lvl
                    if level is None or lvl == level:
                        rows.append(item)
        return rows

    def summarize(self, limit: int = 200, level: str = "task") -> dict[str, Any]:
        runs = self._read_finishes(level=level)[-max(1, limit):]
        if not runs and level == "task":
            runs = self._read_finishes(level=None)[-max(1, limit):]
        total = len(runs)
        success = sum(1 for r in runs if r.get("success"))
        failed = total - success
        avg_latency = (sum(float(r.get("latency_ms", 0.0) or 0.0) for r in runs) / total) if total else 0.0
        avg_fix_rounds = (sum(int(r.get("fix_rounds", 0) or 0) for r in runs) / total) if total else 0.0
        return {
            "window": total,
            "success": success,
            "failed": failed,
            "success_rate": (success / total) if total else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
            "avg_fix_rounds": round(avg_fix_rounds, 2),
            "top_errors": self.top_error_patterns(limit=10, level=level),
            "level": level,
        }

    def top_error_patterns(self, limit: int = 10, level: str | None = "task") -> list[dict[str, Any]]:
        runs = self._read_finishes(level=level)
        if not runs and level == "task":
            runs = self._read_finishes(level=None)
        counts: dict[str, int] = {}
        for r in runs:
            et = (r.get("error_type") or "").strip()
            if not et:
                continue
            counts[et] = counts.get(et, 0) + 1
        return sorted(
            [{"error_type": k, "count": v} for k, v in counts.items()],
            key=lambda x: -x["count"],
        )[:max(1, limit)]
