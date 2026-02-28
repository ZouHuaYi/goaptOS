"""Unified execution result, error, and log protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class ErrorInfo:
    code: str
    message: str
    retriable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
            "details": self.details,
        }


@dataclass(slots=True)
class LogEvent:
    level: str
    event: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "level": self.level,
            "event": self.event,
            "message": self.message,
            "data": self.data,
        }


@dataclass(slots=True)
class ExecutionResult:
    success: bool
    task: str = ""
    code: str = ""
    stdout: str = ""
    stderr: str = ""
    fix_rounds: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    error: ErrorInfo | None = None
    logs: list[LogEvent] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": self.success,
            "task": self.task,
            "code": self.code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "fix_rounds": self.fix_rounds,
            "_metrics": self.metrics,
            "_logs": [x.to_dict() for x in self.logs],
            **self.extra,
        }
        if self.error:
            payload["error"] = self.error.message
            payload["_error"] = self.error.to_dict()
        return payload


def failure_result(task: str, message: str, code: str = "execution_error", retriable: bool = False, **details: Any) -> dict[str, Any]:
    return ExecutionResult(
        success=False,
        task=task,
        fix_rounds=0,
        error=ErrorInfo(code=code, message=message, retriable=retriable, details=details),
    ).to_dict()


def append_log(result: dict[str, Any], level: str, event: str, message: str, **data: Any) -> dict[str, Any]:
    out = dict(result)
    logs = list(out.get("_logs") or [])
    logs.append(LogEvent(level=level, event=event, message=message, data=data).to_dict())
    out["_logs"] = logs
    return out


def normalize_error(error: Any, default_code: str = "runtime_error", retriable: bool = False) -> dict[str, Any]:
    if isinstance(error, dict):
        code = str(error.get("code") or default_code)
        message = str(error.get("message") or error.get("error") or "unknown error")
        details = error.get("details", {})
        return ErrorInfo(code=code, message=message, retriable=bool(error.get("retriable", retriable)), details=details if isinstance(details, dict) else {}).to_dict()
    text = str(error or "unknown error")
    return ErrorInfo(code=default_code, message=text, retriable=retriable).to_dict()


def extract_error_message(result: dict[str, Any]) -> str:
    structured = result.get("_error", {})
    if isinstance(structured, dict) and structured.get("message"):
        return str(structured.get("message"))
    return str(result.get("error") or result.get("stderr") or "")
