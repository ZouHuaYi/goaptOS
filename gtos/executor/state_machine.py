"""Execution state machine for traceable workflow transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class ExecutionState(str, Enum):
    INIT = "INIT"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    RETRYING = "RETRYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.INIT: {ExecutionState.PLANNING, ExecutionState.EXECUTING, ExecutionState.ABORTED},
    ExecutionState.PLANNING: {ExecutionState.EXECUTING, ExecutionState.ABORTED, ExecutionState.FAILED},
    ExecutionState.EXECUTING: {ExecutionState.RETRYING, ExecutionState.SUCCESS, ExecutionState.FAILED, ExecutionState.ABORTED},
    ExecutionState.RETRYING: {ExecutionState.EXECUTING, ExecutionState.SUCCESS, ExecutionState.FAILED, ExecutionState.ABORTED},
    ExecutionState.SUCCESS: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.ABORTED: set(),
}


@dataclass(slots=True)
class StateTransition:
    frm: ExecutionState
    to: ExecutionState
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.frm.value,
            "to": self.to.value,
            "reason": self.reason,
            "meta": self.meta,
            "ts": self.ts,
        }


class ExecutionStateMachine:
    def __init__(self) -> None:
        self._state = ExecutionState.INIT
        self._history: list[StateTransition] = []

    @property
    def current(self) -> ExecutionState:
        return self._state

    def can_transition(self, to_state: ExecutionState) -> bool:
        return to_state in _TRANSITIONS[self._state]

    def transition(self, to_state: ExecutionState, reason: str = "", meta: dict[str, Any] | None = None) -> None:
        if to_state == self._state:
            return
        if not self.can_transition(to_state):
            raise ValueError(f"Invalid state transition: {self._state.value} -> {to_state.value}")
        self._history.append(
            StateTransition(
                frm=self._state,
                to=to_state,
                reason=reason,
                meta=meta or {},
            )
        )
        self._state = to_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self._state.value,
            "history": [x.to_dict() for x in self._history],
        }
