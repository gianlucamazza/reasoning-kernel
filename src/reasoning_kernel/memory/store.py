"""The value store — the interpreter's only place to keep step results.

Holds ``StepId -> TaintedValue``, and resolves a plan ``ArgValue`` (a reference or an inline
literal) into a ``TaintedValue``. Inline literals are labelled trusted: they come from the plan,
which the planner produced having seen only the controlled query (Invariant A).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.plan import ArgRef, ArgValue
from reasoning_kernel.schemas.provenance import ProvenanceLabel
from reasoning_kernel.schemas.values import TaintedValue


class ValueStore:
    def __init__(self) -> None:
        self._values: dict[StepId, TaintedValue] = {}

    def put(self, step_id: StepId, value: TaintedValue) -> None:
        if step_id in self._values:
            raise ValueError(f"step result already stored: {step_id!r}")
        self._values[step_id] = value

    def get(self, step_id: StepId) -> TaintedValue:
        return self._values[step_id]

    def resolve(self, arg: ArgValue) -> TaintedValue:
        if isinstance(arg, ArgRef):
            tv = self._values[arg.ref]
            if arg.path is None:
                return tv
            return TaintedValue(
                value=_navigate(tv.value, arg.path), label=tv.label, produced_by=tv.produced_by
            )
        # Inline literal: derives only from the (trusted) plan.
        return TaintedValue(
            value=arg, label=ProvenanceLabel.trusted(), produced_by=StepId("__literal__")
        )


def _navigate(value: Any, path: str) -> Any:
    cur = value
    for part in path.split("."):
        if isinstance(cur, BaseModel):
            cur = getattr(cur, part)
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise TypeError(f"cannot navigate path {path!r}: {type(cur).__name__} has no {part!r}")
    return cur
