"""EMA-based capability statistics updater."""

from __future__ import annotations

import time
from typing import Any

from gtos.adaptive_engine.capability_registry import CapabilityMeta, CapabilityRegistry


class CapabilityStatsUpdater:
    def __init__(self, registry: CapabilityRegistry, ema_alpha: float = 0.25) -> None:
        self._registry = registry
        self._alpha = float(max(0.01, min(1.0, ema_alpha)))

    def update_from_result(
        self,
        selected_capabilities: list[str],
        result: dict[str, Any],
        assessment: dict[str, Any] | None = None,
    ) -> None:
        names = list(dict.fromkeys(selected_capabilities or []))
        if not names:
            return
        success = bool(result.get("success"))
        latency_ms = float((result.get("_metrics", {}) or {}).get("latency_ms", 0.0) or 0.0)
        retries = self._extract_retries(result)
        token_cost = self._estimate_token_cost(result)
        risk = self._risk_to_num(str((assessment or {}).get("risk_level", "low")))
        for name in names:
            meta = self._registry.get(name)
            meta.usage_count += 1
            meta.success_rate = self._ema(meta.success_rate, 1.0 if success else 0.0)
            meta.avg_time_ms = self._ema(meta.avg_time_ms, latency_ms)
            meta.avg_retries = self._ema(meta.avg_retries, float(retries))
            meta.avg_token_cost = self._ema(meta.avg_token_cost, token_cost)
            meta.risk_level = self._ema(meta.risk_level, risk)
            meta.last_updated = time.time()
            self._registry.update(meta)
        self._registry.save()

    def _ema(self, old: float, new: float) -> float:
        return round((self._alpha * float(new)) + ((1.0 - self._alpha) * float(old)), 6)

    def _extract_retries(self, result: dict[str, Any]) -> int:
        if result.get("summary"):
            return int((result.get("summary", {}) or {}).get("retried_nodes", 0) or 0)
        attempts = int((result.get("_execution", {}) or {}).get("attempts", 1) or 1)
        return max(0, attempts - 1)

    def _estimate_token_cost(self, result: dict[str, Any]) -> float:
        text = "\n".join(
            [
                str(result.get("task", "") or ""),
                str(result.get("code", "") or ""),
                str(result.get("stdout", "") or ""),
                str(result.get("stderr", "") or ""),
            ]
        )
        return float(max(1, len(text) // 4))

    def _risk_to_num(self, risk: str) -> float:
        m = {"low": 0.2, "medium": 0.5, "high": 0.8, "blocked": 1.0}
        return float(m.get((risk or "low").lower(), 0.2))
