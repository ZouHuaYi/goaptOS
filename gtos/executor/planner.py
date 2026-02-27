# gtos/executor/planner.py
"""任务规划层：拆解为子任务列表或 DAG；可选依赖 VectorStore 检索历史经验辅助规划。"""

from typing import Any, Sequence


def decompose(task_prompt: str, vector_store: Any = None, retrieval_top_k: int = 3) -> Sequence[str]:
    """将任务拆成子任务列表。当前：单任务即自身。vector_store 预留供后续扩展。"""
    task = task_prompt.strip()
    if not task:
        return []
    return [task]


def plan_to_dag(
    task_prompt: str,
    vector_store: Any = None,
    retrieval_top_k: int = 5,
) -> list[dict[str, Any]]:
    """返回 DAG 节点列表，每节点含 id、deps、prompt。当前：单节点无依赖。
    若传入 vector_store，检索相似历史任务并写入节点 _retrieved_skills，供执行或后续 LLM 拆解参考。
    """
    task = task_prompt.strip()
    if not task:
        return []
    node: dict[str, Any] = {"id": "1", "deps": [], "prompt": task}
    if vector_store is not None and hasattr(vector_store, "search"):
        try:
            hits = vector_store.search(task, top_k=retrieval_top_k)
            if hits:
                node["_retrieved_skills"] = [{"text": (h.get("text") or "")[:300], "metadata": h.get("metadata", {})} for h in hits]
        except Exception:
            pass
    return [node]


def topo_order(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按依赖拓扑排序；若有环返回空列表。deps 为依赖的节点 id 列表。"""
    id_to_node = {n["id"]: n for n in nodes}
    in_degree = {n["id"]: len([d for d in n.get("deps", []) if d in id_to_node]) for n in nodes}
    queue = [n["id"] for n in nodes if in_degree[n["id"]] == 0]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(id_to_node[nid])
        for n in nodes:
            if nid in n.get("deps", []):
                in_degree[n["id"]] -= 1
                if in_degree[n["id"]] == 0:
                    queue.append(n["id"])
    return order if len(order) == len(nodes) else []
