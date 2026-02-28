# gtos/core/__init__.py
from gtos.core.llm import LLMClient
from gtos.core.interfaces import (
    ErrorInfo,
    ExecutionResult,
    LogEvent,
    PluginLifecycle,
    SkillRecord,
    SkillStoreProtocol,
    TaskExecutor,
    TaskSpec,
    failure_result,
)

__all__ = [
    "ErrorInfo",
    "ExecutionResult",
    "LLMClient",
    "LogEvent",
    "PluginLifecycle",
    "SkillRecord",
    "SkillStoreProtocol",
    "TaskExecutor",
    "TaskSpec",
    "failure_result",
]
