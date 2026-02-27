"""Task orchestration: planning, DAG validation, and execution wrapper."""

from typing import Any

from gtos.executor.dag_runner import run_dag_report
from gtos.executor.planner import plan_to_dag


class TaskOrchestrator:
    def __init__(self, vector_store: Any = None, retrieval_top_k: int = 5) -> None:
        self._vector_store = vector_store
        self._retrieval_top_k = retrieval_top_k

    def plan(self, goal: str, context: dict | None = None) -> list[dict[str, Any]]:
        dag = plan_to_dag(goal, vector_store=self._vector_store, retrieval_top_k=self._retrieval_top_k)
        if len(dag) <= 1:
            decomposed = self._heuristic_decompose(goal)
            if len(decomposed) > 1:
                dag = self._to_chain_dag(decomposed)
        return dag

    def validate_dag(self, dag: list[dict[str, Any]]) -> None:
        ids = set()
        for n in dag:
            nid = n.get("id")
            if not nid:
                raise ValueError("DAG node id is required.")
            if nid in ids:
                raise ValueError(f"Duplicate DAG node id: {nid}")
            ids.add(nid)
        for n in dag:
            for d in n.get("deps", []):
                if d not in ids:
                    raise ValueError(f"Node {n.get('id')} depends on missing node {d}")
                if d == n.get("id"):
                    raise ValueError(f"Node {n.get('id')} cannot depend on itself")

    def execute(
        self,
        dag: list[dict[str, Any]],
        executor: Any,
        plugin_manager: Any,
        parallel: bool = False,
        max_workers: int = 4,
        node_retry_count: int = 0,
        fail_policy: str = "skip",
    ) -> dict[str, Any]:
        self.validate_dag(dag)
        report = run_dag_report(
            dag,
            executor,
            plugin_manager,
            parallel=parallel,
            max_workers=max_workers,
            node_retry_count=node_retry_count,
            fail_policy=fail_policy,
        )
        report["execution_policy"] = {
            "parallel": bool(parallel),
            "max_workers": int(max_workers),
            "node_retry_count": int(node_retry_count),
            "fail_policy": fail_policy,
        }
        return report

    def derive_execution_policy(self, base: dict[str, Any], assessment: dict[str, Any] | None = None) -> dict[str, Any]:
        """根据风险评估动态调整 DAG 执行策略。"""
        b = base or {}
        out = {
            "parallel": bool(b.get("dag_parallel", False)),
            "max_workers": int(b.get("dag_max_workers", 4)),
            "node_retry_count": int(b.get("node_retry_count", 0)),
            "fail_policy": str(b.get("dag_fail_policy", "skip")),
        }
        risk = (assessment or {}).get("risk_level", "low")
        dynamic = (assessment or {}).get("dynamic", {}) or {}
        if risk in {"high", "blocked"}:
            out["parallel"] = False
            out["max_workers"] = 1
            out["fail_policy"] = "stop"
            out["node_retry_count"] = max(out["node_retry_count"], 1)
        elif risk == "medium":
            out["parallel"] = False
            out["max_workers"] = 1
            if out["fail_policy"] == "continue":
                out["fail_policy"] = "skip"
        if dynamic.get("risk_boost") == "high":
            out["parallel"] = False
            out["max_workers"] = 1
            out["fail_policy"] = "stop"
        return out

    def _heuristic_decompose(self, goal: str) -> list[str]:
        text = (goal or "").strip()
        if not text:
            return []
        separators = ["\n", "；", ";", "。然后", " 然后 ", "并且", " and then "]
        parts = [text]
        for sep in separators:
            next_parts = []
            for p in parts:
                if sep in p:
                    next_parts.extend([x.strip() for x in p.split(sep)])
                else:
                    next_parts.append(p.strip())
            parts = [x for x in next_parts if x]
        uniq: list[str] = []
        for p in parts:
            if p and p not in uniq:
                uniq.append(p)
        return uniq[:6]

    def _to_chain_dag(self, tasks: list[str]) -> list[dict[str, Any]]:
        dag: list[dict[str, Any]] = []
        prev = None
        for i, t in enumerate(tasks, start=1):
            nid = str(i)
            deps = [prev] if prev else []
            dag.append({"id": nid, "deps": deps, "prompt": t})
            prev = nid
        return dag
