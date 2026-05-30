"""Deepseek provider — OpenAI-compatible, so it reuses the OpenAI path via ``base_url``.

Concrete proof of the fungibility corollary: a new provider is a subclass + a base URL, with
the entire structured-output / fallback machinery inherited unchanged.
"""

from __future__ import annotations

from typing import Any

from reasoning_kernel.reasoner.openai import OpenAIProvider


class DeepseekProvider(OpenAIProvider):
    name = "deepseek"

    def _build_client(self) -> Any:
        import openai

        from reasoning_kernel.config import settings

        return openai.OpenAI(
            api_key=settings.deepseek_api_key.get_secret_value() or None,
            base_url=settings.deepseek_base_url,
            timeout=settings.llm_timeout_seconds,
        )
