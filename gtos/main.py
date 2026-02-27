# gtos/main.py
"""用户入口：从 config 加载配置 → 注册插件 → 规划任务 → 执行闭环。"""

import argparse
import logging
from pathlib import Path
from gtos.config import load_config
from gtos.core.llm import LLMClient
from gtos.executor import CodeExecutor, PluginManager, SkillStore, decompose, plan_to_dag, run_dag
from gtos.executor.dag_runner import _node_prompt
from gtos.memory import get_vector_store
from gtos.plugins import AgentPlugin, LLMOptimizerPlugin, LoggerPlugin, SkillPlugin


def _setup_logging(level: str) -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=lvl, format="%(levelname)s [%(name)s] %(message)s")


def _build_plugins(config: dict, llm_client: LLMClient) -> tuple[PluginManager, object]:
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
    name_to_plugin = {
        "logger": LoggerPlugin(),
        "skill": SkillPlugin(
            skill_store=skill_store,
            vector_store=vector_store,
            recent_count=skill_cfg.get("recent_count", 3),
            retrieval_top_k=skill_cfg.get("retrieval_top_k", 5),
        ),
        "agent": AgentPlugin(),
        "llm_optimizer": LLMOptimizerPlugin(llm_client=llm_client, refine=llm_opt_cfg.get("refine", False)),
    }
    pm = PluginManager()
    for name in enabled:
        if name in name_to_plugin:
            pm.register(name_to_plugin[name])
    return pm, vector_store


def main(config_path: str | None = None, task_override: str | None = None) -> None:
    config = load_config(config_path)
    _setup_logging(config.get("logging", {}).get("level", "INFO"))

    llm_client = LLMClient(config=config.get("llm", {}))
    plugin_manager, vector_store = _build_plugins(config, llm_client)
    paths = config.get("paths", {})
    exec_cfg = config.get("executor", {})

    code_executor = CodeExecutor(
        llm=llm_client,
        skill_store=SkillStore(path=paths.get("skills_file")),
        max_fix_rounds=exec_cfg.get("max_fix_rounds", 3),
        timeout_seconds=exec_cfg.get("timeout_seconds", 30),
    )

    task_prompt = task_override or config.get("default_task", "用 Python 打印 Hello from gtos 并计算 1+2")
    prompt = plugin_manager.apply_pre_execute(task_prompt)

    exec_cfg = config.get("executor", {})
    use_planner = exec_cfg.get("use_planner", False)
    dag_parallel = exec_cfg.get("dag_parallel", False)
    dag_max_workers = exec_cfg.get("dag_max_workers", 4)

    if use_planner:
        skill_cfg = config.get("plugins", {}).get("skill", {})
        dag = plan_to_dag(prompt, vector_store=vector_store, retrieval_top_k=skill_cfg.get("retrieval_top_k", 5))
        if len(dag) > 1:
            try:
                results = run_dag(dag, code_executor, plugin_manager, parallel=dag_parallel, max_workers=dag_max_workers)
            except Exception as e:
                plugin_manager.apply_on_error(str(e))
                raise
            result = {"success": all(r.get("success") for r in results), "results": results}
        else:
            try:
                result = code_executor.execute_task(_node_prompt(dag[0])) if dag else {}
            except Exception as e:
                plugin_manager.apply_on_error(str(e))
                raise
            result = plugin_manager.apply_post_execute(result)
    else:
        try:
            result = code_executor.execute_task(prompt)
        except Exception as e:
            plugin_manager.apply_on_error(str(e))
            raise
        result = plugin_manager.apply_post_execute(result)

    print("--- result ---")
    if result.get("results"):
        for i, r in enumerate(result["results"]):
            print(f"[{i+1}] success:", r.get("success"), "id:", r.get("id"))
            if r.get("stdout"):
                print("  stdout:", (r["stdout"] or "").strip()[:200])
        print("all success:", result.get("success"))
    else:
        print("success:", result.get("success"))
        if result.get("stdout"):
            print("stdout:", result["stdout"].strip())
        if result.get("stderr"):
            print("stderr:", result["stderr"])
        if result.get("code"):
            print("code (first 3 lines):", result["code"].strip().split("\n")[:3])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GTOS 自动代码生成 + 插件扩展")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径（默认项目根 config.json 或环境变量 GTOS_CONFIG）")
    parser.add_argument("--task", "-t", default=None, help="本次执行的任务描述（覆盖 config 中的 default_task）")
    args = parser.parse_args()
    main(config_path=args.config, task_override=args.task)
