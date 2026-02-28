"""Skill decay and expiry rules."""

from __future__ import annotations

import time
from typing import Any


class SkillDecay:
    def __init__(self, expire_after_days: int = 90, min_active_score: float = 0.18) -> None:
        self._expire_after_days = max(1, int(expire_after_days))
        self._min_active_score = float(min_active_score)

    def apply(self, skill: dict[str, Any], now_ts: float | None = None) -> dict[str, Any]:
        now = now_ts or time.time()
        last_used = float(skill.get("last_used_at", skill.get("created_at", now)) or now)
        idle_days = max(0.0, (now - last_used) / 86400.0)
        score = float(skill.get("score", 0.5) or 0.5)
        fail_count = int(skill.get("fail_count", 0) or 0)
        success_count = int(skill.get("success_count", 0) or 0)

        expired = idle_days >= self._expire_after_days or (score < self._min_active_score and fail_count > success_count + 3)
        skill["expired"] = bool(expired)
        skill["status"] = "expired" if expired else "active"
        skill["idle_days"] = round(idle_days, 2)
        return skill
