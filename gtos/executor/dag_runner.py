# gtos/executor/dag_runner.py
"""按 DAG 顺序或并行执行子任务，并聚合结果。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from gtos.executor.planner import topo_order


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


def run_dag(
    nodes: list[dict[str, Any]],
    code_executor: Any,
    plugin_manager: Any,
    parallel: bool = False,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """按 DAG 执行：parallel=False 严格拓扑序；parallel=True 同层并行。"""
    ordered = topo_order(nodes)
    if not ordered:
        return []
    if not parallel:
        results = []
        for node in ordered:
            prompt = plugin_manager.apply_pre_execute(_node_prompt(node))
            try:
                r = code_executor.execute_task(prompt)
            except Exception as e:
                plugin_manager.apply_on_error(str(e))
                r = {"success": False, "id": node["id"], "error": str(e)}
            r = plugin_manager.apply_post_execute({**r, "id": node["id"], "deps": node.get("deps", [])})
            results.append(r)
        return results

    # 同层并行：按拓扑层分组，层内并行执行
    id_to_node = {n["id"]: n for n in ordered}
    id_to_result: dict[str, dict] = {}
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
                def run_one(nd):
                    prompt = plugin_manager.apply_pre_execute(_node_prompt(nd))
                    try:
                        r = code_executor.execute_task(prompt)
                    except Exception as e:
                        plugin_manager.apply_on_error(str(e))
                        r = {"success": False, "id": nd["id"], "error": str(e)}
                    return plugin_manager.apply_post_execute({**r, "id": nd["id"], "deps": nd.get("deps", [])})
                fut = pool.submit(run_one, node)
                futures[fut] = node["id"]
            for fut in as_completed(futures):
                nid = futures[fut]
                try:
                    id_to_result[nid] = fut.result()
                except Exception as e:
                    id_to_result[nid] = {"success": False, "id": nid, "error": str(e)}
                completed.add(nid)

    return [id_to_result[n["id"]] for n in ordered]
