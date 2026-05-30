"""Deterministic, key-free provider — the test seam.

Scripts responses keyed by the requested schema's name (e.g. ``"Plan"``, ``"EmailSummary"``).
A response is either a prebuilt model instance or a callable ``(prompt) -> model``. This lets a
test script *both* a benign and a malicious plan and prove that the **kernel** — not the model —
is what blocks an attack: the planner can ask for anything; the gate decides what commits.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from reasoning_kernel.reasoner.base import LLMResult, LLMUsage

Response = BaseModel | Callable[[str], BaseModel]


class FakeProvider:
    name = "fake"
    supports_prompt_cache = False
    supports_structured_output = True

    def __init__(
        self,
        responses: dict[str, Response] | None = None,
        *,
        default: Callable[[type[BaseModel], str], BaseModel] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default

    def parse[T: BaseModel](
        self,
        *,
        prompt: str,
        schema: type[T],
        system: str | None,
        model: str,
        max_tokens: int,
        cache_system: bool = True,
    ) -> LLMResult[T]:
        key = schema.__name__
        scripted = self._responses.get(key)
        if scripted is None:
            if self._default is None:
                raise KeyError(f"FakeProvider has no scripted response for schema {key!r}")
            data = self._default(schema, prompt)
        elif callable(scripted):
            data = scripted(prompt)
        else:
            data = scripted
        if not isinstance(data, schema):
            raise TypeError(f"FakeProvider response for {key!r} is not a {key} instance")
        return LLMResult(data=data, usage=LLMUsage(), model="fake", provider="fake", raw=None)
