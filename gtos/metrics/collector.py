"""Execution metrics collector for prompt auto-optimization."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _estimate_tokens(*texts: str) -> int:
    joined = "\n".join([t for t in texts if t])
    if not joined:
        return 0
    return max(1, len(joined) // 4)


class MetricsCollector:
    def __init__(self, metrics_file: str | Path) -> None:
        self._metrics_file = Path(metrics_file)
        self._metrics_file.parent.mkdir(parents=True, exist_ok=True)

    def record_run(self, task_prompt: str, result: dict[str, Any]) -> None:
        row = {
            "ts": time.time(),
            "success": bool(result.get("success")),
            "fix_rounds": int(result.get("fix_rounds", 0) or 0),
            "latency_ms": float((result.get("_metrics", {}) or {}).get("latency_ms", 0.0)),
            "token_in": _estimate_tokens(task_prompt),
            "token_out": _estimate_tokens(
                str(result.get("code", "") or ""),
                str(result.get("stdout", "") or ""),
                str(result.get("stderr", "") or ""),
                str(result.get("error", "") or ""),
            ),
            "error": str(result.get("error") or (result.get("_error", {}) or {}).get("message") or "")[:400],
        }
        with open(self._metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def summarize(self, window: int = 80) -> dict[str, Any]:
        rows = self._read_recent(window=window)
        total = len(rows)
        if total == 0:
            return {
                "samples": 0,
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "avg_fix_rounds": 0.0,
                "avg_latency_ms": 0.0,
                "avg_token_total": 0.0,
            }
        success = sum(1 for r in rows if bool(r.get("success")))
        fix_total = sum(int(r.get("fix_rounds", 0) or 0) for r in rows)
        latency_total = sum(float(r.get("latency_ms", 0.0) or 0.0) for r in rows)
        token_total = sum(int(r.get("token_in", 0) or 0) + int(r.get("token_out", 0) or 0) for r in rows)
        return {
            "samples": total,
            "success_rate": round(success / total, 4),
            "failure_rate": round((total - success) / total, 4),
            "avg_fix_rounds": round(fix_total / total, 4),
            "avg_latency_ms": round(latency_total / total, 2),
            "avg_token_total": round(token_total / total, 2),
        }

    def _read_recent(self, window: int) -> list[dict[str, Any]]:
        if not self._metrics_file.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(self._metrics_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
        if window <= 0:
            return out
        return out[-window:]

