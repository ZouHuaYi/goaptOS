from gtos.main import _decide_tool_activation


def test_tool_activation_on_demand_without_external_need() -> None:
    enabled, reason = _decide_tool_activation(
        "请用 Python 计算 1+2",
        {"tool_activation_mode": "on_demand"},
        {"task_profile": {"requires_external_tool": False}},
    )
    assert enabled is False
    assert "not_required" in reason


def test_tool_activation_on_demand_with_external_need() -> None:
    enabled, reason = _decide_tool_activation(
        "帮我导出 figma 节点",
        {"tool_activation_mode": "on_demand"},
        {"task_profile": {"requires_external_tool": True}},
    )
    assert enabled is True
    assert "requires_external_tool" in reason


def test_tool_activation_mode_always() -> None:
    enabled, reason = _decide_tool_activation(
        "普通任务",
        {"tool_activation_mode": "always"},
        {"task_profile": {"requires_external_tool": False}},
    )
    assert enabled is True
    assert reason == "mode=always"

