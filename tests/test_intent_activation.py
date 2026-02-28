from gtos.main import _decide_intent_activation


def test_intent_activation_on_demand_python_simple() -> None:
    out = _decide_intent_activation(
        "请用 Python 计算 1+2 并打印",
        {"intent_activation": {"mode": "on_demand"}},
        {"task_profile": {"complexity_score": 0.2, "requires_external_tool": False, "requires_parallel": False}},
    )
    assert out["mcp_tools"] is False
    assert out["skill_plugin"] is False
    assert out["agent_plugin"] is False


def test_intent_activation_on_demand_external_tool() -> None:
    out = _decide_intent_activation(
        "请调用 Figma 导出节点",
        {"intent_activation": {"mode": "on_demand"}},
        {"task_profile": {"complexity_score": 0.3, "requires_external_tool": True, "requires_parallel": False}},
    )
    assert out["mcp_tools"] is True


def test_intent_activation_always() -> None:
    out = _decide_intent_activation(
        "普通任务",
        {"intent_activation": {"mode": "always"}},
        {"task_profile": {"complexity_score": 0.1, "requires_external_tool": False, "requires_parallel": False}},
    )
    assert out["mcp_tools"] is True
    assert out["skill_plugin"] is True
    assert out["agent_plugin"] is True
    assert out["llm_optimizer_plugin"] is True

