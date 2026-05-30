"""The tool registry — where the effect callables live, and nowhere else.

A ``RegisteredTool`` binds a declared ``ToolSpec`` to its callable. The registry is the only
holder of callables; it hands them solely to the ``EffectDispatcher``. The interpreter never
receives the registry, so it has no reference path to a callable — half of the by-construction
no-bypass guarantee (the other half is the dispatcher requiring a Gate).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from reasoning_kernel.schemas.registry import ToolSpec

ToolCallable = Callable[[BaseModel], BaseModel]


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    callable: ToolCallable


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, fn: ToolCallable) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name!r}")
        self._tools[spec.name] = RegisteredTool(spec=spec, callable=fn)

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"unknown tool: {name!r}") from None

    def catalog(self) -> list[ToolSpec]:
        """Specs only — names, schemas, effect levels. Safe to show the planner."""
        return [t.spec for t in self._tools.values()]
