"""Structured-output helpers shared by the role wrappers and by factory-based callers.

``call_structured`` drives a held provider instance (used by the role wrappers, which is what
makes the kernel testable with a FakeProvider). ``parse_with_schema`` is the limolane-style
convenience that resolves a provider + model from settings — used by the demo and live tests.
"""

from __future__ import annotations

from pydantic import BaseModel

from reasoning_kernel.reasoner.base import LLMProvider

DEFAULT_MAX_TOKENS = 4096


def call_structured[T: BaseModel](
    provider: LLMProvider,
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    model: str = "fake",
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    result = provider.parse(
        prompt=prompt,
        schema=schema,
        system=system,
        model=model,
        max_tokens=max_tokens,
        cache_system=provider.supports_prompt_cache,
    )
    return result.data


def parse_with_schema[T: BaseModel](
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider

    prov = get_llm_provider(provider)
    effective_model = model or default_model_for(prov.name)
    return call_structured(
        prov, prompt, schema, system=system, model=effective_model, max_tokens=max_tokens
    )
