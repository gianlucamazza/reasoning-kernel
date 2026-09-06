"""Per-invocation metadata capture; no prompts, responses or cross-thread global state."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic import BaseModel

from reasoning_kernel.reasoner.base import LLMResult, LLMUsage


@dataclass(frozen=True)
class CallMetrics:
    provider: str
    model: str
    usage: LLMUsage


_capture: ContextVar[list[CallMetrics] | None] = ContextVar("rk_usage", default=None)


def record[T: BaseModel](result: LLMResult[T]) -> None:
    capture = _capture.get()
    if capture is not None:
        capture.append(CallMetrics(result.provider, result.model, result.usage))


def measure[T](thunk: Callable[[], T]) -> tuple[T, list[CallMetrics]]:
    capture: list[CallMetrics] = []
    token = _capture.set(capture)
    try:
        return thunk(), capture
    finally:
        _capture.reset(token)
