"""The single, replaceable Reasoner interface (the §5.2 fungibility corollary as code).

Every reasoner — privileged planner or quarantined parser, on any provider — is reached only
through ``LLMProvider.parse``. Swapping a model is a factory change, nothing else. The shape
mirrors limolane's ``infra/llm/base.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


class ReasonerError(Exception):
    """A provider failed to return a usable structured result.

    Covers empty/refused/malformed provider responses. The Conductor treats it as a fail-closed
    condition: subsequent work stops. Previously completed or uncertain tool effects remain real.
    """


class TransportError(ReasonerError):
    """The provider call itself failed: rate limit exhausted, 5xx, network fault, SDK timeout,
    or a request the provider rejected outright.

    Subclassing ``ReasonerError`` keeps the Conductor's handling uniform: the run fails closed
    and the trace records a terminal event, instead of the run vanishing behind a raw traceback
    with no audit record.
    """


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
