"""The wrapped value type that flows through the interpreter's value store.

Every result the interpreter produces is a ``TaintedValue``: a payload plus its provenance
label plus the step that produced it. Nothing reaches an effect except as a ``TaintedValue``,
so the Verifier always has a label to reason about.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.provenance import ProvenanceLabel


class TaintedValue(BaseModel):
    """A value carrying its provenance. Frozen; ``value`` is opaque to the kernel."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    value: Any
    label: ProvenanceLabel
    produced_by: StepId
