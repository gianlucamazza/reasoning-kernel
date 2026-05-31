"""The value store — the interpreter's only place to keep step results.

Holds ``StepId -> TaintedValue``, and resolves a plan ``ArgValue`` (a reference or an inline
literal) into a ``TaintedValue``. Inline literals are labelled trusted: they come from the plan,
which the planner produced having seen only the controlled query (Invariant A).

Limit: taint is object-level. Navigating a ``path`` keeps the whole value's label. This is sound
today because every value is produced by a single step (homogeneous provenance). Field-level labels
would be needed only once a value-COMBINING step exists (a hypothetical ``MergeStep`` building one
structure from refs of differing labels); until then one label over-approximates, which is safer.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.plan import ArgRef, ArgValue
from reasoning_kernel.schemas.provenance import ProvenanceLabel
from reasoning_kernel.schemas.values import TaintedValue


class ValueStore:
    def __init__(self, query_label: ProvenanceLabel | None = None) -> None:
        self._values: dict[StepId, TaintedValue] = {}
        # Inline literals derive their label from the run's (trusted) query — see resolve().
        self._query_label = query_label if query_label is not None else ProvenanceLabel.trusted()

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
        # Inline literal: derives from the run's query label (trusted unless the query is not).
        return TaintedValue(value=arg, label=self._query_label, produced_by=StepId("__literal__"))


def _navigate(value: object, path: str) -> object:
    cur: object = value
    for part in path.split("."):
        if isinstance(cur, BaseModel):
            if part not in type(cur).model_fields:
                raise ValueError(
                    f"path {path!r}: {type(cur).__name__} has no field {part!r} "
                    f"(available: {', '.join(type(cur).model_fields)})"
                )
            cur = getattr(cur, part)
        elif isinstance(cur, dict):
            # The kernel treats payloads as opaque: dict values are navigated as plain ``object``.
            cur_dict = cast("dict[str, object]", cur)
            if part not in cur_dict:
                raise ValueError(f"path {path!r}: key {part!r} not in dict")
            cur = cur_dict[part]
        else:
            raise ValueError(f"path {path!r}: {type(cur).__name__} has no {part!r}")
    return cur
