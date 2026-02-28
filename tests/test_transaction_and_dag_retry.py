from pathlib import Path

from gtos.executor.dag_runner import run_dag_report
from gtos.executor.plugin_manager import PluginManager
from gtos.executor.transaction import TaskTransactionManager


class _FailOnceExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute_task(self, task_prompt: str, original_task: str | None = None) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"success": False, "task": original_task or task_prompt, "error": "first attempt failed"}
        return {"success": True, "task": original_task or task_prompt, "stdout": "ok", "fix_rounds": 1}


def test_transaction_manager_checkpoint_and_rollback(tmp_path: Path) -> None:
    tx = TaskTransactionManager(run_id="unit-run", base_dir=tmp_path)
    ck = tx.create_checkpoint("t1", {"prompt": "hello"})
    tx.record_attempt("t1", 1, False, "err")
    tx.rollback("t1", "failed_once")
    tx.finish_task("t1", False)

    task = tx.get_task("t1")
    assert task["checkpoint"]["id"] == ck
    assert task["rolled_back"] is True
    assert len(task["attempts"]) == 1


def test_dag_partial_retry_and_checkpoint_output() -> None:
    dag = [{"id": "1", "deps": [], "prompt": "do thing"}]
    report = run_dag_report(
        dag,
        _FailOnceExecutor(),
        PluginManager(),
        parallel=False,
        node_retry_count=1,
        fail_policy="skip",
    )
    assert report["success"] is True
    assert report["summary"]["retried_nodes"] == 1
    assert "checkpoint_file" in report
    assert Path(report["checkpoint_file"]).exists()
