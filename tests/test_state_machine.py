from gtos.executor.state_machine import ExecutionState, ExecutionStateMachine


def test_state_machine_retry_to_success_flow() -> None:
    sm = ExecutionStateMachine()
    sm.transition(ExecutionState.PLANNING)
    sm.transition(ExecutionState.EXECUTING)
    sm.transition(ExecutionState.RETRYING)
    sm.transition(ExecutionState.SUCCESS)

    payload = sm.to_dict()
    assert payload["current"] == "SUCCESS"
    assert [x["to"] for x in payload["history"]] == ["PLANNING", "EXECUTING", "RETRYING", "SUCCESS"]


def test_state_machine_rejects_invalid_transition() -> None:
    sm = ExecutionStateMachine()
    sm.transition(ExecutionState.EXECUTING)
    sm.transition(ExecutionState.SUCCESS)
    try:
        sm.transition(ExecutionState.RETRYING)
        assert False, "invalid transition should raise"
    except ValueError:
        assert True
