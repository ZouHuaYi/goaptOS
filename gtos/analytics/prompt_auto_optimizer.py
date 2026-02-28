"""Prompt auto-optimizer driven by recent execution metrics."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class PromptAutoOptimizer:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._window = int(cfg.get("window", 60))
        self._min_samples = int(cfg.get("min_samples", 12))
        self._failure_rate_threshold = float(cfg.get("failure_rate_threshold", 0.35))
        self._avg_fix_rounds_threshold = float(cfg.get("avg_fix_rounds_threshold", 1.2))
        self._avg_token_threshold = float(cfg.get("avg_token_threshold", 2600))
        self._state_file = Path(cfg.get("state_file", "data/prompt_state.json"))
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {"profiles": {}, "updated_ts": 0.0}
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                obj = json.load(f)
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
        return {"profiles": {}, "updated_ts": 0.0}

    def optimize(self, metrics: dict[str, Any], current_profiles: dict[str, str] | None = None) -> dict[str, Any]:
        if not self._enabled:
            return {"enabled": False, "applied": False, "profiles": current_profiles or {}, "reason": "disabled"}
        profiles = dict(current_profiles or {})
        samples = int(metrics.get("samples", 0) or 0)
        if samples < self._min_samples:
            return {"enabled": True, "applied": False, "profiles": profiles, "reason": "insufficient_samples", "metrics": metrics}

        fail_rate = float(metrics.get("failure_rate", 0.0))
        avg_fix = float(metrics.get("avg_fix_rounds", 0.0))
        avg_tokens = float(metrics.get("avg_token_total", 0.0))
        applied = False

        if fail_rate >= self._failure_rate_threshold or avg_fix >= self._avg_fix_rounds_threshold:
            profiles["generate_code"] = (
                "You generate runnable Python code only. "
                "Prioritize correctness over brevity. "
                "Include import checks, explicit edge-case handling, and clear output statements. "
                "Return only Python code without markdown fences."
            )
            profiles["fix_code"] = (
                "You repair Python code from runtime errors. "
                "Preserve original intent, fix root cause, and avoid introducing new dependencies unless required. "
                "Return only corrected runnable Python code."
            )
            applied = True

        if avg_tokens >= self._avg_token_threshold:
            profiles["react_step"] = (
                "Return ONLY one compact JSON action object. "
                "Prefer direct code_exec with concise content. "
                "Use finish as soon as a successful execution is observed."
            )
            applied = True

        state = {
            "enabled": True,
            "applied": applied,
            "window": self._window,
            "metrics": metrics,
            "profiles": profiles,
            "updated_ts": time.time(),
        }
        self._save_state(state)
        return state

    @property
    def window(self) -> int:
        return self._window

    def _save_state(self, payload: dict[str, Any]) -> None:
        tmp = self._state_file.with_suffix(self._state_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self._state_file)

