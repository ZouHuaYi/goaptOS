# gtos/executor/code_executor.py
"""核心执行闭环：生成 → 执行 → 出错则修复并重试。"""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from gtos.core.interfaces.result import ErrorInfo, append_log

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

    def execute_task(self, task_prompt: str, original_task: str | None = None) -> dict[str, Any]:
        """执行闭环：生成代码 → 执行 → 失败则用 LLM 修复并重试。"""
        canonical_task = (original_task or task_prompt).strip()
        code = self.llm.generate_code(task_prompt)
        attempt_errors: list[dict[str, Any]] = []
        for round in range(self.max_fix_rounds + 1):
            ok, stdout, stderr = self._run_code(code)
            if ok:
                self.skill_store.add(
                    canonical_task,
                    code,
                    success=True,
                    metadata={"fix_rounds": round, "error": "", "source": "code_executor"},
                )
                out = {
                    "success": True,
                    "task": canonical_task,
                    "_task_prompt": task_prompt,
                    "code": code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "fix_rounds": round,
                    "_execution": {"attempts": round + 1, "had_retry": round > 0, "attempt_errors": attempt_errors},
                }
                out = append_log(
                    out,
                    "info",
                    "executor.code.success",
                    "code execution completed",
                    attempts=round + 1,
                    had_retry=round > 0,
                )
                return out
            error_info = stderr or stdout or "unknown error"
            attempt_errors.append(ErrorInfo(code="exec_failed", message=error_info, retriable=True, details={"round": round}).to_dict())
            if round == self.max_fix_rounds:
                self.skill_store.add(
                    canonical_task,
                    code,
                    success=False,
                    metadata={"fix_rounds": round, "error": error_info, "source": "code_executor"},
                )
                out = {
                    "success": False,
                    "task": canonical_task,
                    "_task_prompt": task_prompt,
                    "code": code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "error": error_info,
                    "_error": ErrorInfo(code="max_fix_rounds_exceeded", message=error_info, retriable=False, details={"round": round}).to_dict(),
                    "fix_rounds": round,
                    "_execution": {"attempts": round + 1, "had_retry": round > 0, "attempt_errors": attempt_errors},
                }
                out = append_log(
                    out,
                    "error",
                    "executor.code.failed",
                    "code execution failed after retries",
                    attempts=round + 1,
                )
                return out
            next_code = self.llm.fix_code(task_prompt, error_info)
            code = next_code
        out = {
            "success": False,
            "task": canonical_task,
            "_task_prompt": task_prompt,
            "error": "max fix rounds exceeded",
            "_error": ErrorInfo(code="max_fix_rounds_exceeded", message="max fix rounds exceeded", retriable=False).to_dict(),
            "fix_rounds": self.max_fix_rounds,
            "_execution": {"attempts": self.max_fix_rounds + 1, "had_retry": self.max_fix_rounds > 0, "attempt_errors": attempt_errors},
        }
        out = append_log(out, "error", "executor.code.failed", "max fix rounds exceeded", attempts=self.max_fix_rounds + 1)
        return out

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
