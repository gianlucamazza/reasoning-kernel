"""Reasoner robustness: provider failures fail closed, and the timeout actually bounds the run.

Two concerns the kernel must not get wrong:
- a provider that returns no usable output (empty/refused/malformed) must abort the run closed,
  never crash and never commit a partial effect;
- ``RunLimits.reasoner_timeout_s`` must abort *promptly* even when the reasoner call hangs — the
  bug being that an executor used as a context manager would block on ``shutdown(wait=True)``.
"""

from __future__ import annotations

import threading
from typing import Any

from conftest import DenyAll
from pydantic import BaseModel

from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import LLMProvider, LLMResult, LLMUsage, ReasonerError
from reasoning_kernel.reasoner.openai import OpenAIProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import CapabilitySet
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import PlanRejected, RunAborted
from reasoning_kernel.tools.registry import ToolRegistry


class _Out(BaseModel):
    x: int = 0


def _interp(provider: LLMProvider, limits: RunLimits) -> tuple[Interpreter, RunContext]:
    ctx = RunContext(
        run_id=RunId("run-x"), user="user@example.com", query=TrustedQuery(text="do it")
    )
    trace = TraceWriter(ctx.run_id)
    grant = CapabilitySet(granted=frozenset())
    dispatcher = EffectDispatcher(ToolRegistry(), Gate(grant, DenyAll()), trace, ctx)
    interp = Interpreter(
        planner=PLLM(provider, grant=grant),
        quarantine=QLLM(provider),
        dispatcher=dispatcher,
        trace=trace,
        q_schemas={},
        limits=limits,
    )
    return interp, ctx


# --- a reasoner that raises must fail closed -----------------------------------------------
class _ErrorProvider:
    name = "error"
    supports_prompt_cache = False
    supports_structured_output = True

    def parse[T: BaseModel](self, *, schema: type[T], **_kwargs: Any) -> LLMResult[T]:
        raise ReasonerError("boom")


def test_reasoner_error_fails_closed() -> None:
    interp, ctx = _interp(_ErrorProvider(), RunLimits())
    result = interp.run(ctx)
    assert result.committed is None
    assert any(isinstance(e, PlanRejected) for e in result.trace.events)


# --- a hung reasoner must abort promptly, not block on shutdown ----------------------------
class _HungProvider:
    name = "hung"
    supports_prompt_cache = False
    supports_structured_output = True

    def __init__(self) -> None:
        self.released = threading.Event()

    def parse[T: BaseModel](self, *, schema: type[T], **_kwargs: Any) -> LLMResult[T]:
        # Block until explicitly released (or a generous safety cap) — simulates a hung call.
        self.released.wait(timeout=10)
        return LLMResult(data=schema(), usage=LLMUsage(), model="hung", provider=self.name)


def test_hung_reasoner_aborts_within_timeout() -> None:
    provider = _HungProvider()
    interp, ctx = _interp(provider, RunLimits(reasoner_timeout_s=0.05))
    try:
        result = interp.run(ctx)
        assert result.committed is None
        aborts = [e for e in result.trace.events if isinstance(e, RunAborted)]
        assert aborts and "exceeded" in aborts[0].reason
    finally:
        provider.released.set()  # let the orphan thread finish so it does not linger


# --- OpenAI provider maps malformed responses to ReasonerError ----------------------------
class _Msg:
    def __init__(self, parsed: BaseModel | None = None, refusal: str | None = None) -> None:
        self.parsed = parsed
        self.refusal = refusal


class _Choice:
    def __init__(self, message: _Msg) -> None:
        self.message = message


class _Completion:
    def __init__(self, choices: list[_Choice]) -> None:
        self.choices = choices
        self.usage = None
        self.model = "fake-model"


class _FakeCompletions:
    def __init__(self, completion: _Completion) -> None:
        self._completion = completion

    def parse(self, **_kwargs: Any) -> _Completion:
        return self._completion


class _FakeChat:
    def __init__(self, completion: _Completion) -> None:
        self.completions = _FakeCompletions(completion)


class _FakeOpenAIClient:
    def __init__(self, completion: _Completion) -> None:
        self.chat = _FakeChat(completion)


def _openai_with(completion: _Completion) -> OpenAIProvider:
    return OpenAIProvider(client=_FakeOpenAIClient(completion))


def _expect_reasoner_error(prov: OpenAIProvider, needle: str) -> None:
    try:
        prov.parse(prompt="p", schema=_Out, system=None, model="m", max_tokens=16)
    except ReasonerError as exc:
        assert needle in str(exc)
    else:
        raise AssertionError("expected ReasonerError")


def test_openai_empty_choices_raises_reasoner_error() -> None:
    _expect_reasoner_error(_openai_with(_Completion(choices=[])), "no choices")


def test_openai_refusal_raises_reasoner_error() -> None:
    _expect_reasoner_error(_openai_with(_Completion([_Choice(_Msg(refusal="nope"))])), "refused")


def test_openai_no_parsed_raises_reasoner_error() -> None:
    _expect_reasoner_error(_openai_with(_Completion([_Choice(_Msg(parsed=None))])), "no parsed")


def test_openai_happy_path_returns_data() -> None:
    prov = _openai_with(_Completion([_Choice(_Msg(parsed=_Out(x=7)))]))
    result = prov.parse(prompt="p", schema=_Out, system=None, model="m", max_tokens=16)
    assert result.data.x == 7
