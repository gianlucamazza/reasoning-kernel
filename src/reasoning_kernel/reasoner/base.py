"""The single, replaceable Reasoner interface (the §5.2 fungibility corollary as code).

Every reasoner — privileged planner or quarantined parser, on any provider — is reached only
through ``LLMProvider.parse``. Swapping a model is a factory change, nothing else. The shape
mirrors limolane's ``infra/llm/base.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMResult[T: BaseModel]:
    data: T
    usage: LLMUsage
    model: str
    provider: str
    raw: Any = None


class LLMProvider(Protocol):
    """Provider-neutral interface for structured-output LLM calls."""

    name: str
    supports_prompt_cache: bool
    supports_structured_output: bool

    def parse[T: BaseModel](
        self,
        *,
        prompt: str,
        schema: type[T],
        system: str | None,
        model: str,
        max_tokens: int,
        cache_system: bool = True,
    ) -> LLMResult[T]: ...
