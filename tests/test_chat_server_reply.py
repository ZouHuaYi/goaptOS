from gtos.web.chat_server import _compose_task_prompt, _extract_detailed_reply, _extract_reply


def test_extract_reply_prefers_stdout_single() -> None:
    reply = _extract_reply({"success": True, "stdout": "42\n"})
    assert "42" in reply


def test_extract_reply_for_dag_without_stdout() -> None:
    reply = _extract_reply(
        {
            "success": True,
            "results": [
                {"id": "1", "success": True, "stdout": ""},
                {"id": "2", "success": False, "error": "boom"},
            ],
            "summary": {"total": 2, "success": 1, "failed": 1, "skipped": 0},
        }
    )
    assert "总计 2" in reply
    assert "[2] 执行失败：boom" in reply


def test_extract_reply_uses_code_when_no_stdout() -> None:
    reply = _extract_reply({"success": True, "code": "print(1)\nprint(2)\n"})
    assert "代码片段" in reply
    assert "print(1)" in reply


def test_extract_detailed_reply_includes_reflection_and_optimizer() -> None:
    reply = _extract_detailed_reply(
        {
            "success": True,
            "stdout": "ok",
            "reflection": {"task_type": "unit", "failure_pattern": "none"},
            "prompt_optimization": {"applied": True, "reason": "threshold"},
        }
    )
    assert "reflection.task_type=unit" in reply
    assert "prompt_optimization.applied=True" in reply


def test_compose_task_prompt_includes_history_block() -> None:
    out = _compose_task_prompt("当前问题", "用户: 你好\n助手: 你好")
    assert "[Conversation History]" in out
    assert "[Current Task]" in out
    assert "当前问题" in out


def test_compose_task_prompt_includes_recalled_block() -> None:
    out = _compose_task_prompt("继续", "", recalled=["用户: 之前讨论过排序优化"])
    assert "[Relevant Past Conversation]" in out
    assert "排序优化" in out
