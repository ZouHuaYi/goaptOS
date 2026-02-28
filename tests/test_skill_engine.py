import time
from pathlib import Path

from gtos.executor.skill_store import SkillStore
from gtos.skill_engine import SkillDecay, SkillEvaluator, SkillVersioning


def test_skill_versioning_increments_by_task_key() -> None:
    skills = [{"task_key": "a", "version": 1}, {"task_key": "a", "version": 2}, {"task_key": "b", "version": 4}]
    assert SkillVersioning.next_version("a", skills) == 3
    assert SkillVersioning.next_version("b", skills) == 5
    assert SkillVersioning.next_version("c", skills) == 1


def test_skill_evaluator_prefers_recent_and_successful_runs() -> None:
    ev = SkillEvaluator(recency_half_life_days=30)
    now = time.time()
    good = {
        "usage_count": 10,
        "success_count": 9,
        "first_pass_success_count": 7,
        "avg_fix_rounds": 0.1,
        "created_at": now - 3600,
        "last_used_at": now - 300,
    }
    bad = {
        "usage_count": 10,
        "success_count": 2,
        "first_pass_success_count": 1,
        "avg_fix_rounds": 2.5,
        "created_at": now - 200 * 86400,
        "last_used_at": now - 120 * 86400,
    }
    assert ev.score(good, now_ts=now) > ev.score(bad, now_ts=now)


def test_skill_decay_marks_expired_when_idle_too_long() -> None:
    decay = SkillDecay(expire_after_days=90, min_active_score=0.2)
    now = time.time()
    skill = {"created_at": now - 200 * 86400, "last_used_at": now - 100 * 86400, "score": 0.8, "fail_count": 0, "success_count": 1}
    out = decay.apply(skill, now_ts=now)
    assert out["expired"] is True
    assert out["status"] == "expired"


def test_skill_store_writes_lifecycle_fields(tmp_path: Path) -> None:
    p = tmp_path / "skills.json"
    store = SkillStore(path=p)
    store.add("print one", "print(1)", success=True, metadata={"fix_rounds": 0})
    store.add("print one", "print(1)\nprint('ok')", success=False, metadata={"fix_rounds": 2, "error": "x"})
    items = store.list_all()
    assert len(items) == 2
    assert all("skill_id" in x for x in items)
    assert all("version" in x for x in items)
    assert all("score" in x for x in items)
    assert sorted([int(x["version"]) for x in items]) == [1, 2]


def test_skill_store_draft_acceptance_flow(tmp_path: Path) -> None:
    p = tmp_path / "skills.json"
    store = SkillStore(path=p)
    store.add("task a", "print('bad')", success=False, metadata={"fix_rounds": 2, "error": "TypeError"})
    draft = store.auto_optimize_from_result({"task": "task a", "success": False, "error": "TypeError"})
    assert draft is not None
    store.add("task a", "print('good')", success=True, metadata={"fix_rounds": 0})
    outcome = store.record_draft_outcome("task a", {"task": "task a", "success": True}, draft_id=draft["draft_id"])
    assert outcome is not None
    assert outcome["status"] == "accepted"
    assert float((outcome.get("acceptance", {}) or {}).get("score_uplift", 0.0)) >= -1.0
