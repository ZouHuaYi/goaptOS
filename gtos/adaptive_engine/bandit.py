"""Bandit engines: UCB + Thompson with bucket orchestration and history."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gtos.adaptive_engine.capability_arm import CapabilityArm


class UCBBandit:
    def __init__(self, exploration_weight: float = 2.0) -> None:
        self.c = float(exploration_weight)
        self.total_pulls = 0
        self.arms: dict[str, CapabilityArm] = {}

    def ensure_arms(self, arm_names: list[str]) -> None:
        for n in arm_names:
            if n not in self.arms:
                self.arms[n] = CapabilityArm(name=n)

    def select_arm(self, available_arms: list[str]) -> tuple[str, dict[str, float]]:
        available = list(dict.fromkeys([x for x in available_arms if x]))
        if not available:
            return "", {}
        self.ensure_arms(available)
        self.total_pulls += 1
        for name in available:
            if self.arms[name].pull_count == 0:
                return name, {name: float("inf")}
        scores: dict[str, float] = {}
        for name in available:
            arm = self.arms[name]
            bonus = self.c * math.sqrt(max(0.0, math.log(max(2, self.total_pulls)) / max(1, arm.pull_count)))
            scores[name] = arm.average_reward + bonus
        best = max(scores, key=scores.get)
        return best, scores

    def update(self, arm_name: str, reward: float) -> None:
        if arm_name not in self.arms:
            self.arms[arm_name] = CapabilityArm(name=arm_name)
        self.arms[arm_name].update(reward)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_pulls": self.total_pulls,
            "exploration_weight": self.c,
            "arms": [a.to_dict() for a in self.arms.values()],
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "UCBBandit":
        obj = UCBBandit(exploration_weight=float(payload.get("exploration_weight", 2.0) or 2.0))
        obj.total_pulls = int(payload.get("total_pulls", 0) or 0)
        for item in payload.get("arms", []):
            if isinstance(item, dict) and item.get("name"):
                arm = CapabilityArm.from_dict(item)
                obj.arms[arm.name] = arm
        return obj


@dataclass(slots=True)
class ThompsonArm:
    name: str
    alpha: float = 1.0
    beta: float = 1.0
    pull_count: int = 0
    total_reward: float = 0.0

    @property
    def average_reward(self) -> float:
        return (self.total_reward / self.pull_count) if self.pull_count > 0 else 0.0

    def update(self, reward: float) -> None:
        self.pull_count += 1
        self.total_reward += float(reward)
        p = max(0.001, min(0.999, (reward + 1.0) / 2.0))
        self.alpha += p
        self.beta += (1.0 - p)

    def sample(self) -> float:
        return random.betavariate(self.alpha, self.beta)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "ThompsonArm":
        return ThompsonArm(
            name=str(payload.get("name", "")),
            alpha=float(payload.get("alpha", 1.0) or 1.0),
            beta=float(payload.get("beta", 1.0) or 1.0),
            pull_count=int(payload.get("pull_count", 0) or 0),
            total_reward=float(payload.get("total_reward", 0.0) or 0.0),
        )


class ThompsonBandit:
    def __init__(self) -> None:
        self.total_pulls = 0
        self.arms: dict[str, ThompsonArm] = {}

    def ensure_arms(self, arm_names: list[str]) -> None:
        for n in arm_names:
            if n not in self.arms:
                self.arms[n] = ThompsonArm(name=n)

    def select_arm(self, available_arms: list[str]) -> tuple[str, dict[str, float]]:
        available = list(dict.fromkeys([x for x in available_arms if x]))
        if not available:
            return "", {}
        self.ensure_arms(available)
        self.total_pulls += 1
        scores = {name: self.arms[name].sample() for name in available}
        best = max(scores, key=scores.get)
        return best, scores

    def update(self, arm_name: str, reward: float) -> None:
        if arm_name not in self.arms:
            self.arms[arm_name] = ThompsonArm(name=arm_name)
        self.arms[arm_name].update(reward)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_pulls": self.total_pulls,
            "arms": [a.to_dict() for a in self.arms.values()],
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "ThompsonBandit":
        obj = ThompsonBandit()
        obj.total_pulls = int(payload.get("total_pulls", 0) or 0)
        for item in payload.get("arms", []):
            if isinstance(item, dict) and item.get("name"):
                arm = ThompsonArm.from_dict(item)
                obj.arms[arm.name] = arm
        return obj


class TaskBucketBandit:
    """Supports UCB/Thompson with `shadow` or `split` A/B modes."""

    def __init__(
        self,
        file_path: str | Path = "data/capability_bandit.json",
        exploration_weight: float = 2.0,
        primary_algo: str = "ucb",
        ab_mode: str = "shadow",
        split_ratio: float = 0.5,
        history_limit: int = 3000,
    ) -> None:
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._exploration_weight = float(exploration_weight)
        self._primary_algo = str(primary_algo or "ucb").lower()
        self._ab_mode = str(ab_mode or "shadow").lower()  # shadow|split
        self._split_ratio = float(max(0.0, min(1.0, split_ratio)))
        self._history_limit = int(max(200, history_limit))
        self._buckets: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._load()

    def select(self, bucket: str, available_arms: list[str], context_key: str = "") -> dict[str, Any]:
        b = self._bucket(bucket)
        algo = self._pick_algo(bucket=bucket, context_key=context_key)
        chosen = b[algo]
        shadow_algo = "thompson" if algo == "ucb" else "ucb"
        shadow = b[shadow_algo]
        arm, scores = chosen.select_arm(available_arms)
        shadow_arm, shadow_scores = shadow.select_arm(available_arms)
        self._save()
        return {
            "bucket": bucket,
            "selected_arm": arm,
            "selected_algo": algo,
            "scores": scores,
            "shadow_arm": shadow_arm,
            "shadow_algo": shadow_algo,
            "shadow_scores": shadow_scores,
        }

    def update(self, bucket: str, arm_name: str, reward: float, selected_algo: str = "ucb") -> None:
        b = self._bucket(bucket)
        b["ucb"].update(arm_name, reward)
        b["thompson"].update(arm_name, reward)
        self._history.append(
            {
                "ts": time.time(),
                "bucket": bucket,
                "selected_algo": selected_algo,
                "arm": arm_name,
                "reward": round(float(reward), 6),
            }
        )
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit :]
        self._save()

    def snapshot(self, top_n: int = 30) -> dict[str, Any]:
        buckets: dict[str, Any] = {}
        for k, bandits in self._buckets.items():
            buckets[k] = {
                "ucb": self._bandit_summary(bandits["ucb"], top_n=top_n),
                "thompson": self._bandit_summary(bandits["thompson"], top_n=top_n),
            }
        return {
            "updated_at": time.time(),
            "exploration_weight": self._exploration_weight,
            "primary_algo": self._primary_algo,
            "ab_mode": self._ab_mode,
            "split_ratio": self._split_ratio,
            "buckets": buckets,
            "history": list(self._history[-200:]),
        }

    def _bandit_summary(self, bandit: Any, top_n: int) -> dict[str, Any]:
        if isinstance(bandit, UCBBandit):
            rows = [
                {
                    "name": a.name,
                    "pull_count": a.pull_count,
                    "total_reward": round(a.total_reward, 6),
                    "average_reward": round(a.average_reward, 6),
                }
                for a in bandit.arms.values()
            ]
            rows.sort(key=lambda x: (-x["average_reward"], -x["pull_count"]))
            return {"total_pulls": bandit.total_pulls, "arms": rows[: max(1, top_n)]}
        rows = [
            {
                "name": a.name,
                "pull_count": a.pull_count,
                "total_reward": round(a.total_reward, 6),
                "average_reward": round(a.average_reward, 6),
                "alpha": round(a.alpha, 6),
                "beta": round(a.beta, 6),
            }
            for a in bandit.arms.values()
        ]
        rows.sort(key=lambda x: (-x["average_reward"], -x["pull_count"]))
        return {"total_pulls": bandit.total_pulls, "arms": rows[: max(1, top_n)]}

    def _bucket(self, name: str) -> dict[str, Any]:
        key = str(name or "default")
        if key not in self._buckets:
            self._buckets[key] = {
                "ucb": UCBBandit(exploration_weight=self._exploration_weight),
                "thompson": ThompsonBandit(),
            }
        return self._buckets[key]

    def _pick_algo(self, bucket: str, context_key: str) -> str:
        if self._ab_mode != "split":
            return self._primary_algo if self._primary_algo in {"ucb", "thompson"} else "ucb"
        seed = f"{bucket}::{context_key or ''}"
        h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        v = int(h[:8], 16) / 0xFFFFFFFF
        return "thompson" if v < self._split_ratio else "ucb"

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return
        self._primary_algo = str(payload.get("primary_algo", self._primary_algo) or self._primary_algo)
        self._ab_mode = str(payload.get("ab_mode", self._ab_mode) or self._ab_mode)
        self._split_ratio = float(payload.get("split_ratio", self._split_ratio) or self._split_ratio)
        self._history = [x for x in payload.get("history", []) if isinstance(x, dict)][-self._history_limit :]
        raw = payload.get("buckets", {}) if isinstance(payload, dict) else {}
        out: dict[str, dict[str, Any]] = {}
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            u = UCBBandit.from_dict(v.get("ucb", {}))
            t = ThompsonBandit.from_dict(v.get("thompson", {}))
            out[str(k)] = {"ucb": u, "thompson": t}
        self._buckets = out

    def _save(self) -> None:
        payload = {
            "updated_at": time.time(),
            "exploration_weight": self._exploration_weight,
            "primary_algo": self._primary_algo,
            "ab_mode": self._ab_mode,
            "split_ratio": self._split_ratio,
            "buckets": {k: {"ucb": v["ucb"].to_dict(), "thompson": v["thompson"].to_dict()} for k, v in self._buckets.items()},
            "history": self._history[-self._history_limit :],
        }
        tmp = self._file_path.with_suffix(self._file_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self._file_path)
