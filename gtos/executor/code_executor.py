# gtos/executor/code_executor.py
"""核心执行闭环：生成 → 执行 → 出错则修复并重试。"""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# 避免循环导入：在运行时从包根取 core
def _get_llm():
    from gtos.config import load_config
    from gtos.core.llm import LLMClient

    cfg = load_config().get("llm", {})
    return LLMClient(config=cfg)

def _get_skill_store():
    from gtos.executor.skill_store import SkillStore
    return SkillStore()


class CodeExecutor:
    """最小稳定单元：只做生成、执行、修错、存技能。"""

    def __init__(
        self,
        llm: Any = None,
        skill_store: Any = None,
        max_fix_rounds: int = 3,
        timeout_seconds: int = 30,
    ) -> None:
        self.llm = llm or _get_llm()
        self.skill_store = skill_store or _get_skill_store()
        self.max_fix_rounds = max_fix_rounds
        self.timeout_seconds = timeout_seconds

    def execute_task(self, task_prompt: str) -> dict[str, Any]:
        """执行闭环：生成代码 → 执行 → 失败则用 LLM 修复并重试。"""
        code = self.llm.generate_code(task_prompt)
        for round in range(self.max_fix_rounds + 1):
            ok, stdout, stderr = self._run_code(code)
            if ok:
                self.skill_store.add(task_prompt, code, success=True)
                return {"success": True, "task": task_prompt, "code": code, "stdout": stdout, "stderr": stderr}
            error_info = stderr or stdout or "unknown error"
            if round == self.max_fix_rounds:
                self.skill_store.add(task_prompt, code, success=False)
                return {"success": False, "task": task_prompt, "code": code, "stdout": stdout, "stderr": stderr, "error": error_info}
            code = self.llm.fix_code(task_prompt, error_info)
        return {"success": False, "task": task_prompt, "error": "max fix rounds exceeded"}

    def _run_code(self, code: str) -> tuple[bool, str, str]:
        """在临时文件中执行 code，返回 (成功, stdout, stderr)。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            path = f.name
        try:
            r = subprocess.run(
                [sys.executable, path],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=Path(path).parent,
            )
            return (r.returncode == 0, r.stdout or "", r.stderr or "")
        finally:
            Path(path).unlink(missing_ok=True)
