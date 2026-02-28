from pathlib import Path

from gtos.adaptive_engine.bandit import TaskBucketBandit
from gtos.adaptive_engine.reward_model import RewardModel


def test_task_bucket_bandit_explores_all_arms_first(tmp_path: Path) -> None:
    b = TaskBucketBandit(file_path=tmp_path / "bandit.json", exploration_weight=2.0, primary_algo="ucb", ab_mode="shadow")
    bucket = "simple:low:python"
    arms = ["single_task", "planner_serial", "planner_parallel"]
    selected = []
    for _ in range(3):
        pick = b.select(bucket, arms, context_key="x")
        arm = pick["selected_arm"]
        selected.append(arm)
        b.update(bucket, arm, reward=0.1, selected_algo=pick.get("selected_algo", "ucb"))
    assert set(selected) == set(arms)


def test_task_bucket_bandit_split_mode_selects_algo_deterministically(tmp_path: Path) -> None:
    b = TaskBucketBandit(file_path=tmp_path / "bandit.json", exploration_weight=2.0, primary_algo="ucb", ab_mode="split", split_ratio=1.0)
    pick = b.select("simple:low:python", ["single_task", "planner_serial"], context_key="same")
    assert pick["selected_algo"] == "thompson"


def test_reward_model_penalizes_latency_and_retries() -> None:
    rm = RewardModel()
    r1 = rm.calculate({"success": True, "_metrics": {"latency_ms": 500}, "_execution": {"attempts": 1}, "task": "a", "code": "print(1)"})
    r2 = rm.calculate({"success": True, "_metrics": {"latency_ms": 5000}, "_execution": {"attempts": 3}, "task": "a", "code": "print(1)"})
    assert r1 > r2
