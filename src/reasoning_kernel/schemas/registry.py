"""Tool specifications — the declared contract the Verifier checks a call against.

A ``ToolSpec`` is pure data: name, typed input/output, the capabilities the call requires,
its effect level, and ``result_readers`` — the capabilities that data RETURNED by the tool
is allowed to flow into. A READ tool that surfaces untrusted content sets
``result_readers=frozenset()`` so its output may flow into no WRITE.

The callable itself is held elsewhere (``tools.registry.RegisteredTool``), never in the schema
layer — so the contract can be inspected and reasoned about without holding the effect.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reasoning_kernel.schemas.capability import Capability, EffectLevel


class ToolSpec(BaseModel):
    """Declared, inspectable contract for one tool. Immutable."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    required_caps: frozenset[Capability]
    effect_level: EffectLevel
    result_readers: frozenset[Capability] = frozenset()
