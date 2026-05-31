"""The ToolRegistry is the sole holder of callables: it rejects duplicates and unknown lookups."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from reasoning_kernel.schemas.capability import Capability, EffectLevel
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.tools.registry import ToolRegistry


class _In(BaseModel):
    pass


class _Out(BaseModel):
    pass


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        input_schema=_In,
        output_schema=_Out,
        required_caps=frozenset({Capability(name="x.do")}),
        effect_level=EffectLevel.WRITE,
    )


def _fn(_inp: BaseModel) -> BaseModel:
    return _Out()


def test_duplicate_registration_is_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_spec("t"), _fn)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_spec("t"), _fn)


def test_unknown_tool_lookup_raises() -> None:
    with pytest.raises(KeyError, match="unknown tool"):
        ToolRegistry().get("nope")


def test_catalog_returns_specs_only() -> None:
    reg = ToolRegistry()
    reg.register(_spec("t"), _fn)
    assert [s.name for s in reg.catalog()] == ["t"]
