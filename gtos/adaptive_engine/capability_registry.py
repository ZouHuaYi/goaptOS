"""Capability metadata registry persisted in JSON."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CapabilityMeta:
    name: str
    success_rate: float = 0.6
    avg_time_ms: float = 1000.0
    avg_retries: float = 0.2
    avg_token_cost: float = 150.0
    risk_level: float = 0.2
    usage_count: int = 0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "CapabilityMeta":
        return CapabilityMeta(
            name=str(payload.get("name", "")),
            success_rate=float(payload.get("success_rate", 0.6) or 0.6),
            avg_time_ms=float(payload.get("avg_time_ms", 1000.0) or 1000.0),
            avg_retries=float(payload.get("avg_retries", 0.2) or 0.2),
            avg_token_cost=float(payload.get("avg_token_cost", 150.0) or 150.0),
            risk_level=float(payload.get("risk_level", 0.2) or 0.2),
            usage_count=int(payload.get("usage_count", 0) or 0),
            last_updated=float(payload.get("last_updated", time.time()) or time.time()),
        )


class CapabilityRegistry:
    def __init__(self, stats_file: str | Path = "data/capability_stats.json") -> None:
        self._stats_file = Path(stats_file)
        self._stats_file.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, CapabilityMeta] = self._load()

    def ensure(self, names: list[str]) -> None:
        changed = False
        for name in names:
            if name not in self._items:
                self._items[name] = CapabilityMeta(name=name)
                changed = True
        if changed:
            self.save()

    def list(self) -> list[CapabilityMeta]:
        return list(self._items.values())

    def get(self, name: str) -> CapabilityMeta:
        if name not in self._items:
            self._items[name] = CapabilityMeta(name=name)
        return self._items[name]

    def update(self, meta: CapabilityMeta) -> None:
        self._items[meta.name] = meta

    def save(self) -> None:
        payload = {
            "updated_at": time.time(),
            "capabilities": [x.to_dict() for x in self.list()],
        }
        tmp = self._stats_file.with_suffix(self._stats_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self._stats_file)

    def _load(self) -> dict[str, CapabilityMeta]:
        if not self._stats_file.exists():
            return {}
        try:
            with open(self._stats_file, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            return {}
        caps = obj.get("capabilities", []) if isinstance(obj, dict) else []
        out: dict[str, CapabilityMeta] = {}
        for item in caps:
            if isinstance(item, dict) and item.get("name"):
                meta = CapabilityMeta.from_dict(item)
                out[meta.name] = meta
        return out
