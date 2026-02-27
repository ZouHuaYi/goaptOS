"""Run-level structured logging (JSONL) for feedback analysis."""

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _now_ts() -> float:
    return time.time()


def _estimate_tokens(*texts: str) -> int:
    joined = "\n".join([t for t in texts if t])
    if not joined:
        return 0
    return max(1, len(joined) // 4)


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


class RunLogger:
    def __init__(self, runs_path: str, metrics_path: str | None = None) -> None:
        self._runs_path = Path(runs_path)
        self._metrics_path = Path(metrics_path) if metrics_path else None
        self._lock = threading.Lock()

    def start_run(self, task: str, prompt: str, meta: dict | None = None) -> str:
        run_id = str(uuid.uuid4())
        m = meta or {}
        event = {
            "event": "run_start",
            "ts": _now_ts(),
            "run_id": run_id,
            "task": task,
            "prompt_hash": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16],
            "prompt_chars": len(prompt or ""),
            "token_estimate_in": _estimate_tokens(prompt or ""),
            "meta": m,
            "level": m.get("level", "node"),
        }
        with self._lock:
            self._append_line(event)
        return run_id

    def finish_run(self, run_id: str, result: dict, error_type: str | None = None, level: str | None = None) -> None:
        event = {
            "event": "run_finish",
            "ts": _now_ts(),
            "run_id": run_id,
            "success": bool(result.get("success")),
            "fix_rounds": int(result.get("fix_rounds", 0) or 0),
            "latency_ms": float((result.get("_metrics", {}) or {}).get("latency_ms", 0.0)),
            "token_estimate_out": _estimate_tokens(result.get("code", ""), result.get("stdout", ""), result.get("stderr", "")),
            "error_type": error_type or self._detect_error_type(result),
            "error": (result.get("error") or result.get("stderr") or "")[:600],
            "level": level or "node",
        }
        with self._lock:
            self._append_line(event)
            self._update_metrics_file_locked()

    def append_event(self, run_id: str, event: str, payload: dict) -> None:
        row = {"event": event, "ts": _now_ts(), "run_id": run_id, "payload": payload}
        with self._lock:
            self._append_line(row)

    def _append_line(self, row: dict[str, Any]) -> None:
        self._runs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._runs_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _detect_error_type(self, result: dict) -> str:
        if result.get("success"):
            return ""
        text = (result.get("error") or result.get("stderr") or "").lower()
        if "timeout" in text:
            return "timeout"
        if "syntaxerror" in text:
            return "syntax_error"
        if "modulenotfounderror" in text:
            return "module_not_found"
        if "typeerror" in text:
            return "type_error"
        if "nameerror" in text:
            return "name_error"
        if text:
            return "runtime_error"
        return "unknown"

    def _update_metrics_file_locked(self) -> None:
        if self._metrics_path is None:
            return
        starts: dict[str, dict[str, Any]] = {}
        finishes: list[dict[str, Any]] = []
        if self._runs_path.exists():
            with open(self._runs_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if row.get("event") == "run_start":
                        starts[row.get("run_id", "")] = row
                    elif row.get("event") == "run_finish":
                        if not row.get("level"):
                            rid = row.get("run_id", "")
                            row["level"] = ((starts.get(rid, {}) or {}).get("meta", {}) or {}).get("level", "node")
                        finishes.append(row)

        task_finishes = [r for r in finishes if r.get("level", "node") == "task"]
        node_finishes = [r for r in finishes if r.get("level", "node") == "node"]
        primary = task_finishes if task_finishes else finishes

        total = len(primary)
        success = sum(1 for r in primary if r.get("success"))
        failed = total - success
        avg_latency = (sum(float(r.get("latency_ms", 0.0) or 0.0) for r in primary) / total) if total else 0.0
        avg_fix_rounds = (sum(int(r.get("fix_rounds", 0) or 0) for r in primary) / total) if total else 0.0
        errors: dict[str, int] = {}
        for r in primary:
            et = (r.get("error_type") or "").strip()
            if et:
                errors[et] = errors.get(et, 0) + 1

        payload = {
            "updated_ts": _now_ts(),
            "runs_total": total,
            "runs_success": success,
            "runs_failed": failed,
            "task_runs_total": len(task_finishes),
            "node_runs_total": len(node_finishes),
            "success_rate": (success / total) if total else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
            "avg_fix_rounds": round(avg_fix_rounds, 2),
            "top_error_types": sorted(
                [{"error_type": k, "count": v} for k, v in errors.items()],
                key=lambda x: -x["count"],
            )[:10],
            "recent_run_ids": [r.get("run_id", "") for r in primary[-20:]],
            "recent_tasks": [starts.get(r.get("run_id", ""), {}).get("task", "")[:120] for r in primary[-20:]],
        }
        _safe_write_json(self._metrics_path, payload)
