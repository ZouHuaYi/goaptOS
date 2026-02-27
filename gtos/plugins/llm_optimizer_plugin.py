# gtos/plugins/llm_optimizer_plugin.py
"""智能增强插件：pre 阶段可选调用 LLM 优化任务描述；on_error 可选返回修复建议。"""

import logging
from gtos.executor.plugin_manager import Plugin

logger = logging.getLogger("gtos")


class LLMOptimizerPlugin(Plugin):
    def __init__(self, llm_client: object | None = None, refine: bool = False) -> None:
        self._llm = llm_client
        self._refine = refine and llm_client is not None

    def pre_execute(self, task_prompt: str) -> str:
        if not self._refine or not self._llm:
            return task_prompt
        try:
            refined = getattr(self._llm, "refine_task", lambda x: x)(task_prompt)
            if refined and refined.strip():
                logger.debug("llm_optimizer: refined prompt (len %d)", len(refined))
                return refined
        except Exception as e:
            logger.warning("llm_optimizer refine failed: %s", e)
        return task_prompt

    def post_execute(self, result: dict) -> dict:
        return result

    def on_error(self, error_info: str) -> str:
        return error_info
