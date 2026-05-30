"""Provider selection. Mirrors limolane's ``infra/llm/factory.py`` (+ deepseek).

The ``fake`` provider is constructed and injected directly in tests, not built here — it needs
a script — so the factory only resolves the real providers.
"""

from __future__ import annotations

from reasoning_kernel.reasoner.base import LLMProvider


def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Return the provider matching ``name``, or the configured default."""
    from reasoning_kernel.config import settings

    provider = name or settings.llm_provider_default
    if provider == "anthropic":
        from reasoning_kernel.reasoner.anthropic import AnthropicProvider

        return AnthropicProvider()
    if provider == "openai":
        from reasoning_kernel.reasoner.openai import OpenAIProvider

        return OpenAIProvider()
    if provider == "deepseek":
        from reasoning_kernel.reasoner.deepseek import DeepseekProvider

        return DeepseekProvider()
    raise ValueError(f"Unknown or non-constructable LLM provider: {provider!r}")


def default_model_for(provider_name: str) -> str:
    from reasoning_kernel.config import settings

    return {
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
        "deepseek": settings.llm_model_deepseek,
    }.get(provider_name, settings.llm_model_anthropic)
