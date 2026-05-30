"""Anthropic-backed provider (structured outputs + ephemeral prompt cache).

Mirrors limolane's ``infra/llm/anthropic.py``. Imported lazily so the package works without
the ``anthropic`` SDK installed (the default test suite uses the FakeProvider).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from reasoning_kernel.reasoner.base import LLMResult, LLMUsage

_BETA = "structured-outputs-2025-11-13"


class AnthropicProvider:
    name = "anthropic"
    supports_prompt_cache = True
    supports_structured_output = True

    def __init__(self, client: Any | None = None) -> None:
        self._client = client  # injection seam for tests

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            from reasoning_kernel.config import settings

            self._client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value() or None,
                timeout=settings.llm_timeout_seconds,
                default_headers={"anthropic-beta": _BETA},
            )
        return self._client

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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_format": schema,
        }
        if system:
            block: dict[str, Any] = {"type": "text", "text": system}
            if cache_system:
                block["cache_control"] = {"type": "ephemeral"}
            kwargs["system"] = [block]

        response = self.client.messages.parse(**kwargs)
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(f"Anthropic returned no parsed output for {schema.__name__}")
        u = response.usage
        usage = LLMUsage(
            input_tokens=getattr(u, "input_tokens", 0),
            output_tokens=getattr(u, "output_tokens", 0),
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0),
        )
        return LLMResult(
            data=parsed,
            usage=usage,
            model=getattr(response, "model", model),
            provider=self.name,
            raw=response,
        )
