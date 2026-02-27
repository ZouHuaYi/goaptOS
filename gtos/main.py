# gtos/main.py
"""用户入口：从 config 加载配置 → 注册插件 → 规划任务 → 执行闭环。"""

import argparse
import logging
import time
from pathlib import Path
from gtos.analytics import RunLogger
from gtos.analytics.strategy_optimizer import StrategyOptimizer
from gtos.cognition import SelfCognition
from gtos.config import load_config
from gtos.core.llm import LLMClient
from gtos.executor import CodeExecutor, PluginManager, SkillStore, TaskOrchestrator
from gtos.memory import get_vector_store
from gtos.observability import GodViewBuilder
from gtos.plugins import AgentPlugin, FeedbackPlugin, LLMOptimizerPlugin, LoggerPlugin, SkillPlugin


def _setup_logging(level: str) -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=lvl, format="%(levelname)s [%(name)s] %(message)s")


def _build_plugins(config: dict, llm_client: LLMClient) -> tuple[PluginManager, object, RunLogger]:
    paths = config.get("paths", {})
    plugins_cfg = config.get("plugins", {})
    memory_cfg = config.get("memory", {}).get("vector_store", {})
    enabled = plugins_cfg.get("enabled", [])
    skill_store = SkillStore(path=paths.get("skills_file"))

    vector_store = None
    if memory_cfg.get("enabled", True):
        backend = memory_cfg.get("backend", "keyword")
        embedding_cfg = memory_cfg.get("embedding", {})
        data_dir = Path(paths["skills_file"]).parent if paths.get("skills_file") else None
        if backend == "chroma":
            persist = memory_cfg.get("persist_path") or (data_dir and str(data_dir / "chroma"))
        else:
            persist = memory_cfg.get("persist_path") or (data_dir and str(data_dir / "skill_vectors.json"))
        try:
            vector_store = get_vector_store(
                backend=backend,
                persist_path=persist,
                embedding_config=embedding_cfg,
                llm_config=config.get("llm", {}),
            )
        except Exception:
            persist = (data_dir and str(data_dir / "skill_vectors.json")) or None
            vector_store = get_vector_store(
                backend="keyword",
                persist_path=persist,
                embedding_config=embedding_cfg,
                llm_config=config.get("llm", {}),
            )

    skill_cfg = plugins_cfg.get("skill", {})
    llm_opt_cfg = plugins_cfg.get("llm_optimizer", {})
    analytics_cfg = config.get("analytics", {})
    run_logger = RunLogger(
        runs_path=analytics_cfg.get("runs_file", "data/runs.jsonl"),
        metrics_path=analytics_cfg.get("metrics_file", "data/metrics.json"),
    )
    name_to_plugin = {
        "logger": LoggerPlugin(),
        "feedback": FeedbackPlugin(run_logger=run_logger),
        "skill": SkillPlugin(
            skill_store=skill_store,
            vector_store=vector_store,
            recent_count=skill_cfg.get("recent_count", 3),
            retrieval_top_k=skill_cfg.get("retrieval_top_k", 5),
            min_relevance=float(skill_cfg.get("min_relevance", 0.22)),
            max_context_chars=int(skill_cfg.get("max_context_chars", 900)),
            ab_test=skill_cfg.get("ab_test", {}),
        ),
        "agent": AgentPlugin(),
        "llm_optimizer": LLMOptimizerPlugin(llm_client=llm_client, refine=llm_opt_cfg.get("refine", False)),
    }
    pm = PluginManager()
    for name in enabled:
        if name in name_to_plugin:
            pm.register(name_to_plugin[name])
    return pm, vector_store, run_logger


def main(config_path: str | None = None, task_override: str | None = None) -> None:
    payload = execute_once(config_path=config_path, task_override=task_override)
    result = payload["result"]
    optimizer_state = payload["optimizer_state"]
    dashboard_path = payload["dashboard_path"]

    print("--- result ---")
    if result.get("results"):
        for i, r in enumerate(result["results"]):
            print(f"[{i+1}] success:", r.get("success"), "id:", r.get("id"))
            if r.get("stdout"):
                print("  stdout:", (r["stdout"] or "").strip()[:200])
        if result.get("summary"):
            s = result["summary"]
            print("summary:", f"total={s.get('total')} success={s.get('success')} failed={s.get('failed')} skipped={s.get('skipped')}")
        if result.get("execution_policy"):
            p = result["execution_policy"]
            print("policy:", f"parallel={p.get('parallel')} workers={p.get('max_workers')} retries={p.get('node_retry_count')} fail_policy={p.get('fail_policy')}")
        if result.get("failure_chain"):
            print("failure_chain:", result.get("failure_chain"))
        print("all success:", result.get("success"))
    else:
        print("success:", result.get("success"))
        if result.get("stdout"):
            print("stdout:", result["stdout"].strip())
        if result.get("stderr"):
            print("stderr:", result["stderr"])
        if result.get("code"):
            print("code (first 3 lines):", result["code"].strip().split("\n")[:3])
        if result.get("rejected"):
            print("rejected:", True)
            print("reason:", result.get("reason"))
            print("risk:", result.get("risk"))
            print("capability_score:", result.get("capability_score"))
    if optimizer_state.get("enabled"):
        print("optimizer:", f"mode={optimizer_state.get('mode')} applied={optimizer_state.get('applied')}")
    if dashboard_path:
        print("god_view:", dashboard_path)


def execute_once(config_path: str | None = None, task_override: str | None = None) -> dict:
    config = load_config(config_path)
    _setup_logging(config.get("logging", {}).get("level", "INFO"))
    optimizer_state = StrategyOptimizer(config.get("optimization", {})).optimize(config)

    llm_client = LLMClient(config=config.get("llm", {}))
    plugin_manager, vector_store, run_logger = _build_plugins(config, llm_client)
    paths = config.get("paths", {})
    exec_cfg = config.get("executor", {})

    code_executor = CodeExecutor(
        llm=llm_client,
        skill_store=SkillStore(path=paths.get("skills_file")),
        max_fix_rounds=exec_cfg.get("max_fix_rounds", 3),
        timeout_seconds=exec_cfg.get("timeout_seconds", 30),
    )

    exec_cfg = config.get("executor", {})
    task_prompt = task_override or config.get("default_task", "用 Python 打印 Hello from gtos 并计算 1+2")
    root_run_id = run_logger.start_run(task_prompt, task_prompt, meta={"phase": "root_task", "level": "task"})
    root_started = time.perf_counter()
    cognition = SelfCognition(config.get("self_cognition", {}))
    assessment = cognition.assess_task(task_prompt)
    decision = cognition.decide(assessment)
    if decision.get("action") == "warn":
        dynamic = assessment.get("dynamic", {}) or {}
        logging.getLogger("gtos").warning(
            "self_cognition warning: risk=%s capability=%.2f reason=%s dynamic_samples=%s dynamic_fail_rate=%s",
            assessment.get("risk_level"),
            float(assessment.get("capability_score", 0.0)),
            decision.get("reason"),
            dynamic.get("samples"),
            dynamic.get("fail_rate"),
        )
    if decision.get("action") == "reject":
        run_logger.finish_run(
            root_run_id,
            {"success": False, "error": decision.get("reason"), "_metrics": {"latency_ms": 0.0}, "fix_rounds": 0},
            error_type="rejected",
            level="task",
        )
        return {
            "result": {
                "success": False,
                "rejected": True,
                "reason": decision.get("reason"),
                "risk": assessment.get("risk_level"),
                "capability_score": assessment.get("capability_score"),
                "dynamic": assessment.get("dynamic"),
            },
            "assessment": assessment,
            "optimizer_state": optimizer_state,
            "dashboard_path": config.get("visualization", {}).get("json_file", "data/dashboard.json"),
            "config": config,
        }

    use_planner = exec_cfg.get("use_planner", False)

    if use_planner:
        skill_cfg = config.get("plugins", {}).get("skill", {})
        orchestrator = TaskOrchestrator(vector_store=vector_store, retrieval_top_k=skill_cfg.get("retrieval_top_k", 5))
        policy = orchestrator.derive_execution_policy(exec_cfg, assessment=assessment)
        dag = orchestrator.plan(task_prompt)
        try:
            result = orchestrator.execute(
                dag,
                code_executor,
                plugin_manager,
                parallel=policy["parallel"],
                max_workers=policy["max_workers"],
                node_retry_count=policy["node_retry_count"],
                fail_policy=policy["fail_policy"],
            )
        except Exception as e:
            plugin_manager.apply_on_error(str(e))
            raise
    else:
        policy = {
            "parallel": False,
            "max_workers": 1,
            "node_retry_count": int(exec_cfg.get("node_retry_count", 0)),
            "fail_policy": "single_task",
        }
        prompt = plugin_manager.apply_pre_execute(task_prompt)
        try:
            result = code_executor.execute_task(prompt, original_task=task_prompt)
        except Exception as e:
            plugin_manager.apply_on_error(str(e))
            raise
        result = plugin_manager.apply_post_execute(result)

    cognition.update_capability(result)
    total_latency_ms = round((time.perf_counter() - root_started) * 1000, 2)
    result.setdefault("_metrics", {})["latency_ms"] = total_latency_ms
    run_logger.finish_run(root_run_id, result, level="task")
    dashboard = GodViewBuilder(config.get("visualization", {})).build(
        last_result=result,
        last_assessment=assessment,
        last_policy=(result.get("execution_policy") or policy),
    )
    return {
        "result": result,
        "assessment": assessment,
        "optimizer_state": optimizer_state,
        "dashboard_path": config.get("visualization", {}).get("json_file", "data/dashboard.json") if dashboard.get("enabled", True) else "",
        "config": config,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GTOS 自动代码生成 + 插件扩展")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径（默认项目根 config.json 或环境变量 GTOS_CONFIG）")
    parser.add_argument("--task", "-t", default=None, help="本次执行的任务描述（覆盖 config 中的 default_task）")
    args = parser.parse_args()
    main(config_path=args.config, task_override=args.task)
