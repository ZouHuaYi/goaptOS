"""Typed runtime events and payload schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventName(str, Enum):
    ON_TASK_START = "on_task_start"
    ON_PLAN_GENERATED = "on_plan_generated"
    ON_THOUGHT = "on_thought"
    ON_ACTION = "on_action"
    ON_EXECUTION_SUCCESS = "on_execution_success"
    ON_EXECUTION_FAILURE = "on_execution_failure"
    ON_REFLECTION_COMPLETE = "on_reflection_complete"
    ON_TASK_END = "on_task_end"


@dataclass
class TaskStartPayload:
    plugins: int


@dataclass
class TaskEndPayload:
    plugins: int


@dataclass
class PlanGeneratedPayload:
    task: str
    dag_nodes: int
    policy: dict[str, Any] = field(default_factory=dict)


@dataclass
class ThoughtPayload:
    task: str
    thought: str
    step: int = 0
    agent: str = ""


@dataclass
class TaskPromptActionPayload:
    task_prompt: str
    type: str = "task_prompt"


@dataclass
class ActionPayload:
    action: dict[str, Any] = field(default_factory=dict)
    task: str = ""
    step: int = 0
    agent: str = ""
    type: str = "action"
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionSuccessPayload:
    result: dict[str, Any]
    task: str = ""
    step: int = 0


@dataclass
class ExecutionFailurePayload:
    error_info: Any
    task: str = ""
    step: int = 0


@dataclass
class ReflectionCompletePayload:
    task: str
    reflection: dict[str, Any]
    result: dict[str, Any]


EventPayload = (
    TaskStartPayload
    | TaskEndPayload
    | PlanGeneratedPayload
    | ThoughtPayload
    | TaskPromptActionPayload
    | ActionPayload
    | ExecutionSuccessPayload
    | ExecutionFailurePayload
    | ReflectionCompletePayload
)


@dataclass
class RuntimeEvent:
    name: EventName
    payload: EventPayload


def event_to_dict(event: RuntimeEvent) -> dict[str, Any]:
    payload = event.payload
    if hasattr(payload, "__dict__"):
        body = dict(payload.__dict__)
    else:
        body = {"value": payload}
    return {
        "name": event.name.value,
        "payload_type": type(payload).__name__,
        "payload": body,
    }


def event_from_dict(obj: dict[str, Any]) -> RuntimeEvent:
    name_raw = str((obj or {}).get("name", "") or "")
    payload_type = str((obj or {}).get("payload_type", "") or "")
    payload = (obj or {}).get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    name = EventName(name_raw)
    cls = _PAYLOAD_CLASS.get(payload_type)
    if cls is None:
        cls = _DEFAULT_BY_EVENT.get(name)
    if cls is None:
        raise ValueError(f"unknown event payload class for {name_raw}/{payload_type}")
    return RuntimeEvent(name=name, payload=cls(**payload))


_PAYLOAD_CLASS = {
    "TaskStartPayload": TaskStartPayload,
    "TaskEndPayload": TaskEndPayload,
    "PlanGeneratedPayload": PlanGeneratedPayload,
    "ThoughtPayload": ThoughtPayload,
    "TaskPromptActionPayload": TaskPromptActionPayload,
    "ActionPayload": ActionPayload,
    "ExecutionSuccessPayload": ExecutionSuccessPayload,
    "ExecutionFailurePayload": ExecutionFailurePayload,
    "ReflectionCompletePayload": ReflectionCompletePayload,
}

_DEFAULT_BY_EVENT = {
    EventName.ON_TASK_START: TaskStartPayload,
    EventName.ON_TASK_END: TaskEndPayload,
    EventName.ON_PLAN_GENERATED: PlanGeneratedPayload,
    EventName.ON_THOUGHT: ThoughtPayload,
    EventName.ON_ACTION: ActionPayload,
    EventName.ON_EXECUTION_SUCCESS: ExecutionSuccessPayload,
    EventName.ON_EXECUTION_FAILURE: ExecutionFailurePayload,
    EventName.ON_REFLECTION_COMPLETE: ReflectionCompletePayload,
}
