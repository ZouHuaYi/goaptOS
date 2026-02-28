"""Action schema and parser for ReAct runtime."""

from __future__ import annotations

import json
from typing import Any

SUPPORTED_ACTION_TYPES = {
    "code_exec",
    "tool_call",
    "memory_query",
    "skill_save",
    "config_update",
    "finish",
}


def _strip_code_fence(text: str) -> str:
    body = (text or "").strip()
    if not body.startswith("```"):
        return body
    lines = body.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return body.replace("```", "").strip()


def parse_action(raw: str) -> dict[str, Any]:
    """Parse model output into action payload.

    Fallback policy:
    1) Try JSON object.
    2) If failed, treat content as a `code_exec` action.
    """
    text = _strip_code_fence(raw)
    obj: dict[str, Any] | None = None
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                obj = parsed
        except Exception:
            obj = None

    if not obj:
        return {"type": "code_exec", "language": "python", "content": raw or ""}

    action_type = str(obj.get("type", "code_exec") or "code_exec").strip().lower()
    if action_type not in SUPPORTED_ACTION_TYPES:
        action_type = "code_exec"
    out = dict(obj)
    out["type"] = action_type
    if action_type == "code_exec":
        out.setdefault("language", "python")
    return out

