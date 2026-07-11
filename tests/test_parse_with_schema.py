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


def test_call_structured_defaults_max_tokens_from_settings() -> None:
    # The RK_LLM_MAX_TOKENS override must actually reach the provider call: max_tokens defaults
    # from settings.llm_max_tokens (single source of truth), not from a module constant.
    from reasoning_kernel.config import settings
    from reasoning_kernel.reasoner.base import LLMResult, LLMUsage
    from reasoning_kernel.reasoner.parse import call_structured

    seen: dict[str, int] = {}

    class _Capturing:
        name = "capturing"
        supports_prompt_cache = False
        supports_structured_output = True

        def parse(self, *, schema: type[_Out], max_tokens: int, **_kw: object) -> LLMResult[_Out]:
            seen["max_tokens"] = max_tokens
            return LLMResult(data=schema(), usage=LLMUsage(), model="m", provider=self.name)

    call_structured(_Capturing(), "p", _Out, model="m")
    assert seen["max_tokens"] == settings.llm_max_tokens

    call_structured(_Capturing(), "p", _Out, model="m", max_tokens=99)
    assert seen["max_tokens"] == 99
