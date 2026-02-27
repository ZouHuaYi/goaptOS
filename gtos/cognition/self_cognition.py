"""Self-cognition layer: task feasibility assessment and boundary decisions."""

import json
from pathlib import Path
from typing import Any


class SelfCognition:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._mode = str(cfg.get("mode", "advise")).strip().lower()
        self._profile_path = Path(cfg.get("profile_file", "data/cognition_profile.json"))
        self._allowed_domains = [str(x).lower() for x in cfg.get("allowed_domains", ["python", "automation", "code_generation"])]
        self._blocked_keywords = [str(x).lower() for x in cfg.get("blocked_keywords", ["rm -rf", "format disk", "wipe", "ransomware"])]
        self._high_risk_keywords = [str(x).lower() for x in cfg.get("high_risk_keywords", ["delete", "drop table", "shutdown", "kill process", "production"])]
        dynamic_cfg = cfg.get("dynamic", {}) if isinstance(cfg.get("dynamic"), dict) else {}
        self._dynamic_enabled = bool(dynamic_cfg.get("enabled", True))
        self._dynamic_runs_path = Path(dynamic_cfg.get("runs_file", "data/runs.jsonl"))
        self._dynamic_window = int(dynamic_cfg.get("window", 200))
        self._dynamic_min_samples = int(dynamic_cfg.get("min_samples", 8))
        self._dynamic_fail_rate_warn = float(dynamic_cfg.get("fail_rate_warn", 0.35))
        self._dynamic_fail_rate_reject = float(dynamic_cfg.get("fail_rate_reject", 0.7))
        self._dynamic_fix_rounds_warn = float(dynamic_cfg.get("avg_fix_rounds_warn", 1.2))
        self._profile = self._load_profile()

    def assess_task(self, task_prompt: str) -> dict[str, Any]:
        text = (task_prompt or "").strip().lower()
        task_type = self._classify_task(text)
        matched_blocked = [k for k in self._blocked_keywords if k in text]
        matched_risky = [k for k in self._high_risk_keywords if k in text]
        capability = self._capability_score(text)
        if matched_blocked:
            risk = "blocked"
        elif matched_risky:
            risk = "high"
        elif capability < 0.35:
            risk = "medium"
        else:
            risk = "low"
        dynamic = self._dynamic_adjustment(task_type)
        risk = self._max_risk(risk, dynamic.get("risk_boost", "low"))
        return {
            "risk_level": risk,
            "capability_score": round(capability, 3),
            "task_type": task_type,
            "matched_blocked": matched_blocked,
            "matched_risky": matched_risky,
            "dynamic": dynamic,
            "mode": self._mode,
        }

    def decide(self, assessment: dict[str, Any]) -> dict[str, Any]:
        risk = assessment.get("risk_level", "low")
        if self._mode == "off":
            return {"action": "allow", "reason": "self_cognition_disabled"}
        if risk == "blocked":
            return {"action": "reject", "reason": "blocked_keywords_matched"}
        if risk == "high":
            if self._mode == "enforce":
                return {"action": "reject", "reason": "high_risk_task"}
            return {"action": "warn", "reason": "high_risk_task"}
        if risk == "medium":
            return {"action": "warn", "reason": "low_capability_confidence"}
        return {"action": "allow", "reason": "within_capability"}

    def update_capability(self, run_result: dict[str, Any]) -> None:
        stats = self._profile.setdefault("stats", {"total": 0, "success": 0, "failed": 0})
        stats["total"] += 1
        if run_result.get("success"):
            stats["success"] += 1
        else:
            stats["failed"] += 1
        self._save_profile()

    def _capability_score(self, text: str) -> float:
        if not text:
            return 0.0
        domain_hit = 0.0
        for d in self._allowed_domains:
            if d in text:
                domain_hit += 1.0
        domain_score = min(1.0, domain_hit / max(1.0, len(self._allowed_domains) * 0.5))
        hist = self._profile.get("stats", {})
        total = float(hist.get("total", 0) or 0.0)
        success = float(hist.get("success", 0) or 0.0)
        history_score = (success / total) if total > 0 else 0.6
        return max(0.0, min(1.0, domain_score * 0.5 + history_score * 0.5))

    def _classify_task(self, text: str) -> str:
        rules = [
            ("database", ["sql", "database", "db", "drop table", "insert", "update", "delete"]),
            ("filesystem", ["file", "path", "directory", "rm", "delete file", "copy", "move"]),
            ("service_ops", ["deploy", "production", "service", "shutdown", "restart", "kill process"]),
            ("network", ["http", "api", "request", "url", "socket", "download"]),
            ("python_code", ["python", "script", "code", "debug", "function"]),
        ]
        for name, keys in rules:
            if any(k in text for k in keys):
                return name
        return "general"

    def _dynamic_adjustment(self, task_type: str) -> dict[str, Any]:
        if not self._dynamic_enabled:
            return {"enabled": False, "risk_boost": "low"}
        starts: dict[str, str] = {}
        finishes: list[dict[str, Any]] = []
        if self._dynamic_runs_path.exists():
            try:
                with open(self._dynamic_runs_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        if row.get("event") == "run_start":
                            starts[row.get("run_id", "")] = str(row.get("task", "") or "")
                        elif row.get("event") == "run_finish":
                            finishes.append(row)
            except Exception:
                return {"enabled": True, "risk_boost": "low", "error": "runs_parse_failed"}
        finishes = finishes[-max(1, self._dynamic_window):]
        total = 0
        failed = 0
        fix_rounds = 0.0
        for r in finishes:
            rid = r.get("run_id", "")
            task_text = starts.get(rid, "").lower()
            if self._classify_task(task_text) != task_type:
                continue
            total += 1
            if not r.get("success"):
                failed += 1
            fix_rounds += float(r.get("fix_rounds", 0) or 0)

        if total < self._dynamic_min_samples:
            return {
                "enabled": True,
                "risk_boost": "low",
                "samples": total,
                "reason": "insufficient_samples",
            }

        fail_rate = failed / total if total else 0.0
        avg_fix = fix_rounds / total if total else 0.0
        boost = "low"
        if fail_rate >= self._dynamic_fail_rate_reject:
            boost = "high"
        elif fail_rate >= self._dynamic_fail_rate_warn or avg_fix >= self._dynamic_fix_rounds_warn:
            boost = "medium"
        return {
            "enabled": True,
            "risk_boost": boost,
            "samples": total,
            "fail_rate": round(fail_rate, 3),
            "avg_fix_rounds": round(avg_fix, 3),
        }

    def _max_risk(self, base: str, incoming: str) -> str:
        order = {"low": 0, "medium": 1, "high": 2, "blocked": 3}
        inv = {v: k for k, v in order.items()}
        b = order.get(base, 0)
        i = order.get(incoming, 0)
        return inv[max(b, i)]

    def _load_profile(self) -> dict[str, Any]:
        if not self._profile_path.exists():
            return {"stats": {"total": 0, "success": 0, "failed": 0}}
        try:
            with open(self._profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"stats": {"total": 0, "success": 0, "failed": 0}}

    def _save_profile(self) -> None:
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._profile_path.with_suffix(self._profile_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._profile, f, ensure_ascii=False, indent=2)
        tmp.replace(self._profile_path)
