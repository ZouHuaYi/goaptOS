# gtos/main.py
"""用户入口：从 config 加载配置 → 注册插件 → 规划任务 → 执行闭环。"""

import argparse
import logging
import time
from pathlib import Path
from gtos.agents import AgentOrchestrator, CoderAgent, MemoryAgent, PlannerAgent, ReviewerAgent
from gtos.adaptive_engine import (
    AdaptiveDecisionEngine,
    CapabilityRegistry,
    CapabilityStatsUpdater,
    RewardModel,
    TaskBucketBandit,
)
from gtos.analytics import RunLogger
from gtos.analytics.prompt_auto_optimizer import PromptAutoOptimizer
from gtos.analytics.strategy_optimizer import StrategyOptimizer
from gtos.cognition import SelfCognition
from gtos.config import load_config
from gtos.core.events import EventName, PlanGeneratedPayload, ReflectionCompletePayload
from gtos.core.interfaces.result import append_log, normalize_error
from gtos.core.llm import LLMClient
from gtos.executor import CodeExecutor, PluginManager, SkillStore, TaskOrchestrator
from gtos.executor.state_machine import ExecutionState, ExecutionStateMachine
from gtos.executor.transaction import TaskTransactionManager
from gtos.memory import MemoryManager, get_vector_store
from gtos.metrics import MetricsCollector
from gtos.observability import GodViewBuilder
from gtos.plugins import (
    AgentPlugin,
    EventRecorderPlugin,
    FeedbackPlugin,
    LLMOptimizerPlugin,
    LoggerPlugin,
    SkillPlugin,
    ThirdPartyPluginLoader,
)
from gtos.runtime import ReActLoop, ReflectionEngine


def _setup_logging(level: str) -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=lvl, format="%(levelname)s [%(name)s] %(message)s")


def _build_plugins(
    config: dict,
    llm_client: LLMClient,
    enabled_plugins: list[str] | None = None,
    run_logger: RunLogger | None = None,
) -> tuple[PluginManager, object, RunLogger]:
    paths = config.get("paths", {})
    plugins_cfg = config.get("plugins", {})
    third_party_cfg = plugins_cfg.get("third_party", {}) if isinstance(plugins_cfg.get("third_party", {}), dict) else {}
    event_recorder_cfg = plugins_cfg.get("event_recorder", {}) if isinstance(plugins_cfg.get("event_recorder", {}), dict) else {}
    memory_cfg = config.get("memory", {}).get("vector_store", {})
    enabled = enabled_plugins or plugins_cfg.get("enabled", [])
    if bool(event_recorder_cfg.get("enabled", False)) and "event_recorder" not in enabled:
        enabled = list(enabled) + ["event_recorder"]
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
    run_logger = run_logger or RunLogger(
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
        "event_recorder": EventRecorderPlugin(
            trace_file=event_recorder_cfg.get("trace_file", "data/runtime_events.jsonl"),
            enabled=bool(event_recorder_cfg.get("enabled", False)),
        ),
    }
    pm = PluginManager()
    for name in enabled:
        if name in name_to_plugin:
            pm.register(name_to_plugin[name])
    if bool(third_party_cfg.get("enabled", True)):
        root_dir = third_party_cfg.get("dir", str(Path.cwd() / "plugins" / "third_party"))
        loader = ThirdPartyPluginLoader(root_dir=root_dir)
        discovered = loader.discover()
        for manifest in discovered:
            plugin_obj = loader.instantiate(
                manifest,
                context={
                    "llm_client": llm_client,
                    "run_logger": run_logger,
                    "vector_store": vector_store,
                    "skill_store": skill_store,
                    "config": config,
                },
            )
            if plugin_obj is not None:
                pm.register(plugin_obj)
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
    state_machine = ExecutionStateMachine()
    config = load_config(config_path)
    _setup_logging(config.get("logging", {}).get("level", "INFO"))
    optimizer_state = StrategyOptimizer(config.get("optimization", {})).optimize(config)
    prompt_auto_cfg = ((config.get("optimization", {}) or {}).get("prompt_auto", {}) or {})
    prompt_optimizer = PromptAutoOptimizer(prompt_auto_cfg if isinstance(prompt_auto_cfg, dict) else {})
    metrics_collector = MetricsCollector(
        (prompt_auto_cfg or {}).get("metrics_file", "data/prompt_metrics.jsonl")
        if isinstance(prompt_auto_cfg, dict)
        else "data/prompt_metrics.jsonl"
    )

    llm_client = LLMClient(config=config.get("llm", {}))
    persisted_prompt_state = prompt_optimizer.load_state()
    persisted_profiles = persisted_prompt_state.get("profiles", {}) if isinstance(persisted_prompt_state, dict) else {}
    if isinstance(persisted_profiles, dict) and persisted_profiles:
        llm_client.set_prompt_overrides(persisted_profiles)
    paths = config.get("paths", {})
    exec_cfg = config.get("executor", {})
    task_prompt = task_override or config.get("default_task", "用 Python 打印 Hello from gtos 并计算 1+2")

    code_executor = CodeExecutor(
        llm=llm_client,
        skill_store=SkillStore(path=paths.get("skills_file")),
        max_fix_rounds=exec_cfg.get("max_fix_rounds", 3),
        timeout_seconds=exec_cfg.get("timeout_seconds", 30),
    )

    adaptive_cfg = config.get("adaptive_engine", {})
    adaptive_enabled = bool(adaptive_cfg.get("enabled", True))
    capability_stats_file = adaptive_cfg.get("stats_file", "data/capability_stats.json")
    capability_bandit_file = adaptive_cfg.get("bandit_file", "data/capability_bandit.json")
    registry = CapabilityRegistry(stats_file=capability_stats_file)
    bandit = TaskBucketBandit(
        file_path=capability_bandit_file,
        exploration_weight=float(adaptive_cfg.get("exploration_weight", 2.0)),
        primary_algo=str(adaptive_cfg.get("primary_algo", "ucb")),
        ab_mode=str(adaptive_cfg.get("ab_mode", "shadow")),
        split_ratio=float(adaptive_cfg.get("split_ratio", 0.5)),
    )
    reward_model = RewardModel()
    stats_updater = CapabilityStatsUpdater(registry=registry, ema_alpha=float(adaptive_cfg.get("ema_alpha", 0.25)))

    analytics_cfg = config.get("analytics", {})
    run_logger = RunLogger(
        runs_path=analytics_cfg.get("runs_file", "data/runs.jsonl"),
        metrics_path=analytics_cfg.get("metrics_file", "data/metrics.json"),
    )

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
        state_machine.transition(ExecutionState.ABORTED, reason="self_cognition_reject", meta={"reason": decision.get("reason", "")})
        reject_error = normalize_error(decision.get("reason") or "self cognition rejected task", default_code="self_cognition_reject", retriable=False)
        reject_result = {
            "success": False,
            "rejected": True,
            "reason": reject_error.get("message"),
            "_error": reject_error,
            "risk": assessment.get("risk_level"),
            "capability_score": assessment.get("capability_score"),
            "dynamic": assessment.get("dynamic"),
            "execution_state": state_machine.current.value,
            "state_history": state_machine.to_dict().get("history", []),
        }
        run_logger.finish_run(
            root_run_id,
            {"success": False, "error": reject_error.get("message"), "_error": reject_error, "_metrics": {"latency_ms": 0.0}, "fix_rounds": 0},
            error_type="rejected",
            level="task",
        )
        prompt_opt_state: dict = {}
        if bool(prompt_auto_cfg.get("enabled", True)) if isinstance(prompt_auto_cfg, dict) else True:
            metrics_collector.record_run(task_prompt=task_prompt, result=reject_result)
            summary = metrics_collector.summarize(window=prompt_optimizer.window)
            prompt_opt_state = prompt_optimizer.optimize(
                metrics=summary,
                current_profiles=llm_client.get_prompt_profiles(),
            )
            reject_result["prompt_optimization"] = prompt_opt_state
        return {
            "result": reject_result,
            "assessment": assessment,
            "optimizer_state": optimizer_state,
            "dashboard_path": config.get("visualization", {}).get("json_file", "data/dashboard.json"),
            "config": config,
        }

    use_planner = exec_cfg.get("use_planner", False)
    adaptive_decision: dict = {}
    plugin_enabled = config.get("plugins", {}).get("enabled", [])
    selected_plugins = list(plugin_enabled)
    if adaptive_enabled:
        adaptive_engine = AdaptiveDecisionEngine(registry=registry, bandit=bandit)
        adaptive_decision = adaptive_engine.decide(
            task_prompt=task_prompt,
            assessment=assessment,
            enabled_plugins=plugin_enabled,
            exec_cfg=exec_cfg,
        )
        selected_plugins = adaptive_decision.get("selected_plugins", selected_plugins)
        overrides = adaptive_decision.get("execution_overrides", {})
        exec_cfg = {**exec_cfg, **overrides}
        use_planner = bool(overrides.get("use_planner", use_planner))

    plugin_manager, vector_store, run_logger = _build_plugins(
        config,
        llm_client,
        enabled_plugins=selected_plugins,
        run_logger=run_logger,
    )
    memory_manager = MemoryManager(
        sqlite_db=paths.get("sqlite_db", "data/gtos.db"),
        vector_store=vector_store,
        skill_store=code_executor.skill_store,
    )
    plugin_manager.start()

    if use_planner:
        state_machine.transition(ExecutionState.PLANNING, reason="planner_enabled")
        skill_cfg = config.get("plugins", {}).get("skill", {})
        orchestrator = TaskOrchestrator(vector_store=vector_store, retrieval_top_k=skill_cfg.get("retrieval_top_k", 5))
        policy = orchestrator.derive_execution_policy(exec_cfg, assessment=assessment)
        dag = orchestrator.plan(task_prompt)
        plugin_manager.event_bus.emit_name(
            EventName.ON_PLAN_GENERATED,
            PlanGeneratedPayload(task=task_prompt, dag_nodes=len(dag), policy=policy),
        )
        state_machine.transition(ExecutionState.EXECUTING, reason="dag_execution_start", meta={"nodes": len(dag)})
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
            state_machine.transition(ExecutionState.ABORTED, reason="dag_execution_exception", meta={"error": str(e)})
            plugin_manager.apply_on_error(normalize_error(str(e), default_code="dag_execution_exception", retriable=False))
            plugin_manager.shutdown()
            raise
    else:
        runtime_cfg = config.get("runtime", {})
        multi_agent_cfg = runtime_cfg.get("multi_agent", {}) if isinstance(runtime_cfg.get("multi_agent"), dict) else {}
        profiles = multi_agent_cfg.get("profiles", {}) if isinstance(multi_agent_cfg.get("profiles"), dict) else {}
        policy = {
            "parallel": False,
            "max_workers": 1,
            "node_retry_count": int(exec_cfg.get("node_retry_count", 0)),
            "fail_policy": "single_task",
        }
        tx_manager = TaskTransactionManager(run_id=f"single-{int(time.time() * 1000)}")
        checkpoint_id = tx_manager.create_checkpoint("single_task", {"prompt": task_prompt})
        state_machine.transition(ExecutionState.EXECUTING, reason="single_task_execution_start")
        prompt = plugin_manager.apply_pre_execute(task_prompt)
        try:
            if bool(multi_agent_cfg.get("enabled", False)):
                loop = ReActLoop(
                    llm=llm_client,
                    code_executor=code_executor,
                    event_bus=plugin_manager.event_bus,
                    max_steps=int(runtime_cfg.get("max_steps", 6)),
                )
                orchestrator = AgentOrchestrator(
                    planner=PlannerAgent(role="planner", profile=profiles.get("planner", {})),
                    coder=CoderAgent(role="coder", profile=profiles.get("coder", {})),
                    reviewer=ReviewerAgent(role="reviewer", profile=profiles.get("reviewer", {})),
                    memory_agent=MemoryAgent(role="memory", profile=profiles.get("memory", {})),
                    event_bus=plugin_manager.event_bus,
                )
                result = orchestrator.execute(
                    prompt,
                    mode=str(multi_agent_cfg.get("mode", "planner_executor_reviewer")),
                    max_rounds=int(multi_agent_cfg.get("max_rounds", 2)),
                    context={
                        "llm": llm_client,
                        "react_loop": loop if bool(runtime_cfg.get("react_enabled", True)) else None,
                        "code_executor": code_executor,
                        "memory": vector_store,
                        "memory_manager": memory_manager,
                        "original_task": task_prompt,
                    },
                )
            elif bool(runtime_cfg.get("react_enabled", True)):
                loop = ReActLoop(
                    llm=llm_client,
                    code_executor=code_executor,
                    event_bus=plugin_manager.event_bus,
                    max_steps=int(runtime_cfg.get("max_steps", 6)),
                )
                result = loop.run(prompt, original_task=task_prompt)
            else:
                result = code_executor.execute_task(prompt, original_task=task_prompt)
        except Exception as e:
            state_machine.transition(ExecutionState.ABORTED, reason="single_task_exception", meta={"error": str(e)})
            tx_manager.record_attempt("single_task", 1, False, str(e))
            tx_manager.rollback("single_task", "execution_exception")
            tx_manager.finish_task("single_task", False, meta={"checkpoint_id": checkpoint_id})
            plugin_manager.apply_on_error(normalize_error(str(e), default_code="single_task_exception", retriable=False))
            plugin_manager.shutdown()
            raise
        attempts = int(result.get("_execution", {}).get("attempts", 1) or 1)
        errors = result.get("_execution", {}).get("attempt_errors", [])
        for i in range(attempts):
            err_msg = ""
            if i < len(errors):
                err_msg = str(errors[i].get("message", ""))
            tx_manager.record_attempt("single_task", i + 1, bool(result.get("success")) and i == attempts - 1, err_msg)
        if not result.get("success"):
            tx_manager.rollback("single_task", "single_task_failed")
        tx_manager.finish_task(
            "single_task",
            bool(result.get("success")),
            meta={"checkpoint_id": checkpoint_id, "attempts": attempts},
        )
        result = plugin_manager.apply_post_execute(result)
        result = append_log(
            result,
            level="info",
            event="executor.single_task.finished",
            message="single task execution finished",
            success=bool(result.get("success")),
            attempts=attempts,
        )
        result["_transaction"] = {
            "run_id": tx_manager.run_id,
            "checkpoint_file": tx_manager.path,
            "task": tx_manager.get_task("single_task"),
        }
        if bool(runtime_cfg.get("reflection_enabled", True)):
            reflector = ReflectionEngine(
                llm=llm_client,
                output_file=runtime_cfg.get("reflection_file", "data/reflections.jsonl"),
                skill_store=code_executor.skill_store,
                vector_store=vector_store,
                memory_manager=memory_manager,
            )
            reflection = reflector.reflect(task=task_prompt, result=result, trace=result.get("react_trace", []))
            result["reflection"] = reflection
            plugin_manager.event_bus.emit_name(
                EventName.ON_REFLECTION_COMPLETE,
                ReflectionCompletePayload(task=task_prompt, reflection=reflection, result=result),
            )

    cognition.update_capability(result)
    if result.get("summary", {}).get("retried_nodes", 0) > 0 or result.get("_execution", {}).get("had_retry"):
        state_machine.transition(ExecutionState.RETRYING, reason="retry_detected")
    state_machine.transition(ExecutionState.SUCCESS if result.get("success") else ExecutionState.FAILED)
    result = append_log(
        result,
        level="info",
        event="executor.run.finished",
        message="run finished with final state",
        final_state=state_machine.current.value,
        success=bool(result.get("success")),
    )
    result["execution_state"] = state_machine.current.value
    result["state_history"] = state_machine.to_dict().get("history", [])
    if adaptive_decision:
        result["adaptive_decision"] = adaptive_decision
    total_latency_ms = round((time.perf_counter() - root_started) * 1000, 2)
    result.setdefault("_metrics", {})["latency_ms"] = total_latency_ms
    if adaptive_enabled and adaptive_decision:
        selected_caps = list(dict.fromkeys((adaptive_decision.get("selected_plugins", []) or []) + (["planner"] if use_planner else ["single_task"]) + (["parallel_dag"] if policy.get("parallel") else [])))
        stats_updater.update_from_result(selected_caps, result=result, assessment=assessment)
        bandit_info = adaptive_decision.get("bandit", {}) if isinstance(adaptive_decision, dict) else {}
        bucket = str(bandit_info.get("bucket", "") or "")
        selected_arm = str(bandit_info.get("selected_combo_arm", "") or bandit_info.get("selected_arm", "") or "")
        selected_algo = str(bandit_info.get("selected_algo", "ucb") or "ucb")
        if bucket and selected_arm:
            reward = reward_model.calculate(result)
            bandit.update(bucket=bucket, arm_name=selected_arm, reward=reward, selected_algo=selected_algo)
            result.setdefault("adaptive_decision", {}).setdefault("bandit", {})["reward"] = reward
    run_logger.finish_run(root_run_id, result, level="task")
    prompt_opt_state: dict = {}
    if bool(prompt_auto_cfg.get("enabled", True)) if isinstance(prompt_auto_cfg, dict) else True:
        metrics_collector.record_run(task_prompt=task_prompt, result=result)
        summary = metrics_collector.summarize(window=prompt_optimizer.window)
        prompt_opt_state = prompt_optimizer.optimize(
            metrics=summary,
            current_profiles=llm_client.get_prompt_profiles(),
        )
        if prompt_opt_state.get("applied"):
            llm_client.set_prompt_overrides(prompt_opt_state.get("profiles", {}))
        result["prompt_optimization"] = prompt_opt_state
    dashboard = GodViewBuilder(config.get("visualization", {})).build(
        last_result=result,
        last_assessment=assessment,
        last_policy=(result.get("execution_policy") or policy),
    )
    plugin_manager.shutdown()
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
