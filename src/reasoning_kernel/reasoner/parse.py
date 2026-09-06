"""Structured-output helpers shared by the role wrappers and by factory-based callers.

``call_structured`` drives a held provider instance (used by the role wrappers, which is what
makes the kernel testable with a FakeProvider). ``parse_with_schema`` is the limolane-style
convenience that resolves a provider + model from settings — used by the demo and live tests.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from reasoning_kernel.reasoner.base import LLMProvider, ReasonerError
from reasoning_kernel.reasoner.telemetry import record


def _default_max_tokens() -> int:
    # Single source of truth: settings.llm_max_tokens (RK_LLM_MAX_TOKENS). Imported lazily, like
    # everywhere else settings is consumed, to keep package import side-effect free.
    from reasoning_kernel.config import settings

    return settings.llm_max_tokens


def call_structured[T: BaseModel](
    provider: LLMProvider,
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    model: str,
    max_tokens: int | None = None,
) -> T:
    if max_tokens is None:
        max_tokens = _default_max_tokens()
    result = provider.parse(
        prompt=prompt,
        schema=schema,
        system=system,
        model=model,
        max_tokens=max_tokens,
        cache_system=provider.supports_prompt_cache,
    )
    record(result)
    # Provider adapters are replaceable: validate the boundary even for prebuilt model instances.
    if not isinstance(result.data, schema):
        raise ReasonerError("provider returned the wrong output model")
    try:
        return schema.model_validate(result.data.model_dump(by_alias=False), by_name=True)
    except ValidationError:
        raise ReasonerError("provider returned invalid structured output") from None


def parse_with_schema[T: BaseModel](
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_tokens: int | None = None,
) -> T:
    from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider

    prov = get_llm_provider(provider)
    effective_model = model or default_model_for(prov.name)
    return call_structured(
        prov, prompt, schema, system=system, model=effective_model, max_tokens=max_tokens
    )
