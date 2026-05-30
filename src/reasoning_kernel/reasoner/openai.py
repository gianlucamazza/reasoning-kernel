"""OpenAI-backed provider, with a JSON-mode fallback for non-strict schemas.

Mirrors limolane's ``infra/llm/openai.py``: prefer strict structured output
(``chat.completions.parse``); on a strict-schema 400 fall back to JSON mode with local
Pydantic validation, so the Plan IR parses identically across providers. Deepseek subclasses
this (OpenAI-compatible API via ``base_url``). Imported lazily.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from reasoning_kernel.reasoner.base import LLMResult, LLMUsage


def _is_strict_schema_error(exc: Exception) -> bool:
    return "response_format" in str(exc).lower()


class OpenAIProvider:
    name = "openai"
    supports_prompt_cache = False  # OpenAI does prefix caching server-side; no client marker
    supports_structured_output = True

    def __init__(self, client: Any | None = None) -> None:
        self._client = client  # injection seam for tests

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> Any:
        import openai

        from reasoning_kernel.config import settings

        return openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value() or None,
            timeout=settings.llm_timeout_seconds,
        )

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
        import openai

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            completion = self.client.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=schema,
                max_completion_tokens=max_tokens,
            )
            choice = completion.choices[0]
            if choice.message.refusal:
                raise RuntimeError(
                    f"provider refused structured response: {choice.message.refusal}"
                )
            parsed = choice.message.parsed
            if parsed is None:
                raise RuntimeError("provider returned no parsed content")
        except openai.BadRequestError as exc:
            if not _is_strict_schema_error(exc):
                raise
            completion, parsed = self._parse_json_mode(messages, schema, model, max_tokens)

        u = getattr(completion, "usage", None)
        usage = LLMUsage(
            input_tokens=getattr(u, "prompt_tokens", 0) if u else 0,
            output_tokens=getattr(u, "completion_tokens", 0) if u else 0,
        )
        return LLMResult(
            data=parsed,
            usage=usage,
            model=getattr(completion, "model", model),
            provider=self.name,
            raw=completion,
        )

    def _parse_json_mode[T: BaseModel](
        self,
        messages: list[dict[str, Any]],
        schema: type[T],
        model: str,
        max_tokens: int,
    ) -> tuple[Any, T]:
        schema_json = json.dumps(schema.model_json_schema())
        msgs = [
            *messages,
            {
                "role": "system",
                "content": (
                    "Return ONLY a JSON object conforming to this JSON Schema "
                    f"(no prose, no markdown):\n{schema_json}"
                ),
            },
        ]
        completion = self.client.chat.completions.create(
            model=model,
            messages=msgs,
            response_format={"type": "json_object"},
            max_completion_tokens=max_tokens,
        )
        content = completion.choices[0].message.content or ""
        return completion, schema.model_validate_json(content)
