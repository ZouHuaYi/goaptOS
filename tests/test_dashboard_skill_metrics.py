import json
from pathlib import Path

from gtos.observability.dashboard import GodViewBuilder


def test_dashboard_includes_skill_lifecycle_and_drafts(tmp_path: Path) -> None:
    runs = tmp_path / "runs.jsonl"
    runs.write_text("", encoding="utf-8")
    skills = tmp_path / "skills.json"
    drafts = tmp_path / "skill_drafts.json"
    skills.write_text(
        json.dumps(
            [
                {"task": "a", "task_key": "a", "version": 1, "score": 0.9, "expired": False, "status": "active", "created_at": 1, "last_used_at": 2},
                {"task": "a", "task_key": "a", "version": 2, "score": 0.3, "expired": False, "status": "active", "created_at": 3, "last_used_at": 4},
                {"task": "b", "task_key": "b", "version": 1, "score": 0.1, "expired": True, "status": "expired", "created_at": 5, "last_used_at": 6},
            ]
        ),
        encoding="utf-8",
    )
    drafts.write_text(
        json.dumps(
            [
                {"draft_id": "d1", "status": "proposed"},
                {"draft_id": "d2", "status": "accepted", "acceptance": {"score_uplift": 0.2}},
            ]
        ),
        encoding="utf-8",
    )
    out_json = tmp_path / "dashboard.json"
    out_md = tmp_path / "dashboard.md"
    gb = GodViewBuilder(
        {
            "enabled": True,
            "runs_file": str(runs),
            "json_file": str(out_json),
            "markdown_file": str(out_md),
            "skills_file": str(skills),
            "skill_drafts_file": str(drafts),
        }
    )
    payload = gb.build(last_result={"success": True})
    assert payload["skill_lifecycle"]["total"] == 3
    assert payload["skill_lifecycle"]["expired"] == 1
    assert payload["skill_drafts"]["proposed"] == 1
    assert payload["skill_drafts"]["acceptance_rate"] == 0.5
    assert payload["skill_drafts"]["avg_score_uplift"] == 0.2
