"""Skill versioning helpers."""

from __future__ import annotations

import hashlib
from typing import Any


class SkillVersioning:
    @staticmethod
    def build_task_key(task: str) -> str:
        return " ".join((task or "").strip().lower().split())[:240]

    @staticmethod
    def build_skill_id(task: str, code: str) -> str:
        raw = f"{SkillVersioning.build_task_key(task)}::{(code or '').strip()[:300]}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def next_version(task_key: str, skills: list[dict[str, Any]]) -> int:
        versions = [int(s.get("version", 1) or 1) for s in skills if str(s.get("task_key", "")) == str(task_key)]
        return (max(versions) + 1) if versions else 1
