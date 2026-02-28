"""Capability runtime primitives."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(slots=True)
class ToolCapability:
    name: str
    source: str
    description: str
    input_schema: dict[str, Any]
    constraints: dict[str, Any] = field(default_factory=dict)

    def execute(self, params: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError


class CapabilityRuntimeRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolCapability] = {}

    def register(self, capability: ToolCapability) -> None:
        self._tools[capability.name] = capability

    def list_tools(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in self._tools.values():
            out.append(
                {
                    "name": c.name,
                    "source": c.source,
                    "description": c.description,
                    "input_schema": c.input_schema,
                    "constraints": c.constraints,
                }
            )
        out.sort(key=lambda x: x["name"])
        return out

    def execute(self, name: str, params: dict[str, Any] | None = None) -> Any:
        cap = self._tools.get(name)
        if cap is None:
            raise KeyError(f"capability_not_found: {name}")
        return cap.execute(params or {})
