"""Unified core interfaces for tasks, skills, plugins, and results."""

from gtos.core.interfaces.plugin import PluginLifecycle
from gtos.core.interfaces.result import ErrorInfo, ExecutionResult, LogEvent, failure_result
from gtos.core.interfaces.skill import SkillRecord, SkillStoreProtocol
from gtos.core.interfaces.task import TaskExecutor, TaskSpec

__all__ = [
    "ErrorInfo",
    "ExecutionResult",
    "LogEvent",
    "PluginLifecycle",
    "SkillRecord",
    "SkillStoreProtocol",
    "TaskExecutor",
    "TaskSpec",
    "failure_result",
]
