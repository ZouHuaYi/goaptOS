from gtos.skill_engine.optimizer import SkillOptimizer


def test_skill_optimizer_creates_draft_for_low_score(tmp_path) -> None:
    opt = SkillOptimizer(drafts_path=tmp_path / "drafts.json", low_score_threshold=0.4, min_fail_count=1)
    skill = {
        "task": "calculate sum",
        "task_key": "calculate sum",
        "code": "print(1+2)",
        "skill_id": "abc",
        "version": 2,
        "score": 0.2,
        "fail_count": 3,
        "success_count": 1,
    }
    result = {"task": "calculate sum", "error": "TypeError: bad operand"}
    assert opt.should_optimize(skill) is True
    draft = opt.build_draft(skill, result)
    opt.save_draft(draft)
    summary = opt.summarize_drafts()
    assert summary["total"] == 1
    assert summary["proposed"] == 1
    assert summary["recent"][0]["target_version"] == 3


def test_skill_optimizer_acceptance_updates_metrics(tmp_path) -> None:
    opt = SkillOptimizer(drafts_path=tmp_path / "drafts.json")
    skill = {"task": "x", "task_key": "x", "code": "print(1)", "skill_id": "s1", "version": 1, "score": 0.2, "fail_count": 3, "success_count": 0}
    draft = opt.build_draft(skill, {"task": "x", "error": "bad"})
    opt.save_draft(draft)
    opt.update_draft_status(
        draft["draft_id"],
        status="accepted",
        extra={"acceptance": {"before_score": 0.2, "accepted_score": 0.6, "score_uplift": 0.4}},
    )
    summary = opt.summarize_drafts()
    assert summary["accepted"] == 1
    assert summary["acceptance_rate"] == 1.0
    assert summary["avg_score_uplift"] == 0.4
