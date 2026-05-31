"""``parse_with_schema`` resolves a provider from the factory and returns the parsed model.

The factory is monkeypatched to hand back a scripted ``FakeProvider`` so the convenience path is
exercised key-free. ``parse_with_schema`` imports the factory at call time, so patching the factory
module attribute takes effect.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import reasoning_kernel.reasoner.factory as factory
from reasoning_kernel.reasoner.base import LLMProvider
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.parse import parse_with_schema


class _Out(BaseModel):
    x: int = 0


def test_parse_with_schema_routes_through_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider({"_Out": _Out(x=7)})

    def _fake_provider(name: str | None = None) -> LLMProvider:
        return fake

    monkeypatch.setattr(factory, "get_llm_provider", _fake_provider)

    out = parse_with_schema("summarize this", _Out, provider="anything")
    assert out.x == 7
