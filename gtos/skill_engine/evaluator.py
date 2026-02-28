"""Skill scoring model."""

from __future__ import annotations

import math
import time
from typing import Any


class SkillEvaluator:
    def __init__(self, recency_half_life_days: int = 30) -> None:
        self._half_life_days = max(1, int(recency_half_life_days))

    def score(self, skill: dict[str, Any], now_ts: float | None = None) -> float:
        now = now_ts or time.time()
        runs = int(skill.get("usage_count", 0) or 0)
        success = int(skill.get("success_count", 0) or 0)
        first_pass = int(skill.get("first_pass_success_count", 0) or 0)
        avg_fix_rounds = float(skill.get("avg_fix_rounds", 0.0) or 0.0)
        last_used = float(skill.get("last_used_at", skill.get("created_at", now)) or now)
        age_days = max(0.0, (now - last_used) / 86400.0)

        success_rate = (success / runs) if runs else 0.5
        first_pass_rate = (first_pass / runs) if runs else 0.5
        recency = math.exp(-math.log(2.0) * (age_days / float(self._half_life_days)))
        usage_confidence = min(1.0, runs / 20.0)
        fix_penalty = max(0.0, min(1.0, avg_fix_rounds / 3.0))

        base = 0.5 * success_rate + 0.2 * first_pass_rate + 0.2 * recency + 0.1 * usage_confidence
        out = base - 0.15 * fix_penalty
        return round(max(0.0, min(1.0, out)), 4)

    def update_run_stats(self, skill: dict[str, Any], success: bool, fix_rounds: int = 0, now_ts: float | None = None) -> dict[str, Any]:
        now = now_ts or time.time()
        runs = int(skill.get("usage_count", 0) or 0) + 1
        success_count = int(skill.get("success_count", 0) or 0) + (1 if success else 0)
        fail_count = int(skill.get("fail_count", 0) or 0) + (0 if success else 1)
        first_pass_success_count = int(skill.get("first_pass_success_count", 0) or 0) + (1 if success and int(fix_rounds) == 0 else 0)
        total_fix_rounds = int(skill.get("total_fix_rounds", 0) or 0) + max(0, int(fix_rounds))

        skill["usage_count"] = runs
        skill["success_count"] = success_count
        skill["fail_count"] = fail_count
        skill["first_pass_success_count"] = first_pass_success_count
        skill["total_fix_rounds"] = total_fix_rounds
        skill["avg_fix_rounds"] = round(total_fix_rounds / runs, 4) if runs else 0.0
        skill["last_used_at"] = now
        skill["score"] = self.score(skill, now_ts=now)
        return skill
