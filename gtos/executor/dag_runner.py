# gtos/executor/dag_runner.py
"""按 DAG 顺序或并行执行子任务，并聚合结果。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import Any

from gtos.core.interfaces.result import append_log, normalize_error
from gtos.executor.planner import topo_order
from gtos.executor.transaction import TaskTransactionManager


def _node_prompt(node: dict[str, Any]) -> str:
    """若节点含 Planner 检索的 _retrieved_skills，则拼入 prompt 供执行参考。"""
    base = node.get("prompt", "")
    skills = node.get("_retrieved_skills")
    if not skills:
        return base
    lines = ["[Reference: similar past tasks]"]
    for s in skills[:3]:
        lines.append("- " + (s.get("text") or "")[:200])
    lines.append("")
    lines.append("[Current task]")
    lines.append(base)
    return "\n".join(lines)


def _execute_node(
    node: dict[str, Any],
    code_executor: Any,
    plugin_manager: Any,
    node_retry_count: int,
    tx_manager: TaskTransactionManager,
) -> dict[str, Any]:
    prompt = plugin_manager.apply_pre_execute(_node_prompt(node))
    attempts = 0
    started = time.perf_counter()
    last: dict[str, Any] = {}
    checkpoint_id = tx_manager.create_checkpoint(
        task_id=str(node["id"]),
        payload={"prompt": node.get("prompt", ""), "deps": node.get("deps", [])},
    )

    while attempts <= max(0, node_retry_count):
        attempts += 1
        try:
            r = code_executor.execute_task(prompt, original_task=node.get("prompt", ""))
        except Exception as e:
            normalized = plugin_manager.apply_on_error(str(e))
            err = normalize_error(normalized, default_code="node_execution_exception", retriable=True)
            r = {"success": False, "id": node["id"], "error": err.get("message", str(e)), "_error": err}
        last = r
        tx_manager.record_attempt(
            task_id=str(node["id"]),
            attempt=attempts,
            success=bool(r.get("success")),
            error=str(r.get("error", "")),
        )
        if r.get("success"):
            break
        tx_manager.rollback(task_id=str(node["id"]), reason="attempt_failed")

    latency_ms = (time.perf_counter() - started) * 1000
    tx_manager.finish_task(
        task_id=str(node["id"]),
        success=bool(last.get("success")),
        meta={"attempts": attempts, "latency_ms": round(latency_ms, 2)},
    )
    tx_meta = tx_manager.get_task(str(node["id"]))
    out = plugin_manager.apply_post_execute(
        {
            **last,
            "id": node["id"],
            "deps": node.get("deps", []),
            "attempts": attempts,
            "_metrics": {**(last.get("_metrics", {}) if isinstance(last, dict) else {}), "node_latency_ms": round(latency_ms, 2)},
            "_transaction": {
                "run_id": tx_manager.run_id,
                "checkpoint_id": checkpoint_id,
                "rolled_back": bool(tx_meta.get("rolled_back")),
                "attempts": tx_meta.get("attempts", []),
            },
        }
    )
    out = append_log(
        out,
        level="info",
        event="executor.dag.node_finished",
        message="dag node finished",
        node_id=str(node["id"]),
        success=bool(out.get("success")),
        attempts=attempts,
    )
    out.setdefault("_node", {})["attempts"] = attempts
    out["_node"]["latency_ms"] = round(latency_ms, 2)
    return out


def _build_report(ordered: list[dict[str, Any]], id_to_result: dict[str, dict], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    results = [id_to_result[n["id"]] for n in ordered]
    success_count = sum(1 for r in results if r.get("success"))
    skipped_count = sum(1 for r in results if r.get("skipped"))
    failed_count = len(results) - success_count - skipped_count
    failure_chain = [r["id"] for r in results if (not r.get("success")) and (not r.get("skipped"))]
    return {
        "success": failed_count == 0 and skipped_count == 0,
        "results": results,
        "summary": {
            "total": len(results),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
        },
        "failure_chain": failure_chain,
        "timeline": timeline,
    }


def run_dag_report(
    nodes: list[dict[str, Any]],
    code_executor: Any,
    plugin_manager: Any,
    parallel: bool = False,
    max_workers: int = 4,
    node_retry_count: int = 0,
    fail_policy: str = "skip",
) -> dict[str, Any]:
    """按 DAG 执行并返回结构化报告。fail_policy: stop | skip | continue"""
    ordered = topo_order(nodes)
    if not ordered:
        return {
            "success": False,
            "results": [],
            "summary": {"total": 0, "success": 0, "failed": 0, "skipped": 0},
            "failure_chain": [],
            "timeline": [],
            "error": "invalid dag (cycle or empty)",
        }

    fail_policy = fail_policy if fail_policy in {"stop", "skip", "continue"} else "skip"
    run_id = f"dag-{int(time.time() * 1000)}"
    tx_manager = TaskTransactionManager(run_id=run_id)
    id_to_result: dict[str, dict] = {}
    timeline: list[dict[str, Any]] = []

    if not parallel:
        for node in ordered:
            dep_fail = any((not id_to_result.get(d, {}).get("success", False)) for d in node.get("deps", []))
            if dep_fail and fail_policy == "skip":
                skipped = {
                    "id": node["id"],
                    "deps": node.get("deps", []),
                    "success": False,
                    "skipped": True,
                    "error": "skipped_due_to_failed_dependencies",
                    "_node": {"attempts": 0, "latency_ms": 0.0},
                }
                id_to_result[node["id"]] = skipped
                timeline.append({"id": node["id"], "status": "skipped"})
                continue

            r = _execute_node(node, code_executor, plugin_manager, node_retry_count=node_retry_count, tx_manager=tx_manager)
            id_to_result[node["id"]] = r
            timeline.append({"id": node["id"], "status": "success" if r.get("success") else "failed"})

            if not r.get("success") and fail_policy == "stop":
                for n in ordered:
                    if n["id"] not in id_to_result:
                        id_to_result[n["id"]] = {
                            "id": n["id"],
                            "deps": n.get("deps", []),
                            "success": False,
                            "skipped": True,
                            "error": "skipped_due_to_stop_policy",
                            "_node": {"attempts": 0, "latency_ms": 0.0},
                        }
                break

        report = _build_report(ordered, id_to_result, timeline)
        retried_nodes = sum(1 for r in report.get("results", []) if int(r.get("attempts", 1) or 1) > 1)
        report.setdefault("summary", {})["retried_nodes"] = retried_nodes
        report["checkpoint_file"] = tx_manager.path
        return report

    completed = set()

    def ready(n: dict) -> bool:
        return all(d in completed for d in n.get("deps", []))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while len(completed) < len(ordered):
            batch = [n for n in ordered if n["id"] not in completed and ready(n)]
            if not batch:
                break

            futures = {}
            for node in batch:
                dep_fail = any((not id_to_result.get(d, {}).get("success", False)) for d in node.get("deps", []))
                if dep_fail and fail_policy == "skip":
                    id_to_result[node["id"]] = {
                        "id": node["id"],
                        "deps": node.get("deps", []),
                        "success": False,
                        "skipped": True,
                        "error": "skipped_due_to_failed_dependencies",
                        "_node": {"attempts": 0, "latency_ms": 0.0},
                    }
                    completed.add(node["id"])
                    timeline.append({"id": node["id"], "status": "skipped"})
                    continue

                fut = pool.submit(_execute_node, node, code_executor, plugin_manager, node_retry_count, tx_manager)
                futures[fut] = node["id"]

            for fut in as_completed(futures):
                nid = futures[fut]
                try:
                    id_to_result[nid] = fut.result()
                except Exception as e:
                    err = normalize_error(str(e), default_code="dag_future_exception", retriable=False)
                    id_to_result[nid] = {
                        "success": False,
                        "id": nid,
                        "error": err["message"],
                        "_error": err,
                        "_node": {"attempts": 1, "latency_ms": 0.0},
                    }
                completed.add(nid)
                timeline.append({"id": nid, "status": "success" if id_to_result[nid].get("success") else "failed"})

                if not id_to_result[nid].get("success") and fail_policy == "stop":
                    for n in ordered:
                        if n["id"] not in id_to_result:
                            id_to_result[n["id"]] = {
                                "id": n["id"],
                                "deps": n.get("deps", []),
                                "success": False,
                                "skipped": True,
                                "error": "skipped_due_to_stop_policy",
                                "_node": {"attempts": 0, "latency_ms": 0.0},
                            }
                    completed = set(n["id"] for n in ordered)
                    break

    report = _build_report(ordered, id_to_result, timeline)
    retried_nodes = sum(1 for r in report.get("results", []) if int(r.get("attempts", 1) or 1) > 1)
    report.setdefault("summary", {})["retried_nodes"] = retried_nodes
    report["checkpoint_file"] = tx_manager.path
    return report


def run_dag(
    nodes: list[dict[str, Any]],
    code_executor: Any,
    plugin_manager: Any,
    parallel: bool = False,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """兼容接口：返回结果列表。"""
    return run_dag_report(
        nodes,
        code_executor,
        plugin_manager,
        parallel=parallel,
        max_workers=max_workers,
    )["results"]
