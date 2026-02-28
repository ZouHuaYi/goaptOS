import json

import pytest

from gtos.main import _load_dag_override


def test_load_dag_override_from_array(tmp_path) -> None:
    dag_file = tmp_path / "dag.json"
    dag_file.write_text(json.dumps([{"id": "1", "deps": [], "prompt": "task"}], ensure_ascii=False), encoding="utf-8")
    nodes, policy = _load_dag_override(str(dag_file))
    assert len(nodes) == 1
    assert nodes[0]["id"] == "1"
    assert policy == {}


def test_load_dag_override_with_policy(tmp_path) -> None:
    dag_file = tmp_path / "dag_with_policy.json"
    payload = {
        "nodes": [{"id": "n1", "deps": [], "prompt": "task"}],
        "execution_policy": {
            "parallel": True,
            "max_workers": 4,
            "node_retry_count": 3,
            "fail_policy": "continue",
        },
    }
    dag_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    nodes, policy = _load_dag_override(str(dag_file))
    assert nodes[0]["id"] == "n1"
    assert policy["parallel"] is True
    assert policy["max_workers"] == 4
    assert policy["node_retry_count"] == 3
    assert policy["fail_policy"] == "continue"


def test_load_dag_override_rejects_invalid_type(tmp_path) -> None:
    dag_file = tmp_path / "bad.json"
    dag_file.write_text(json.dumps("not valid dag", ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        _load_dag_override(str(dag_file))
