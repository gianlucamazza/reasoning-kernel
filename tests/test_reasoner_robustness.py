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
from reasoning_kernel.reasoner.anthropic import AnthropicProvider
from reasoning_kernel.reasoner.base import (
    LLMProvider,
    LLMResult,
    LLMUsage,
    ReasonerError,
    TransportError,
)
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
    # model= is explicit: these providers have test-only names ("error", "hung") that the strict
    # default_model_for resolution rightly refuses to resolve.
    interp = Interpreter(
        planner=PLLM(provider, model="test-model", grant=grant),
        quarantine=QLLM(provider, model="test-model"),
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


# --- transport faults map to TransportError (a ReasonerError → the run fails closed) --------
class _RaisingCompletions:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def parse(self, **_kwargs: Any) -> Any:
        raise self._exc

    def create(self, **_kwargs: Any) -> Any:
        raise self._exc


class _RaisingOpenAIClient:
    def __init__(self, exc: Exception) -> None:
        self.chat = _FakeChat.__new__(_FakeChat)
        self.chat.completions = _RaisingCompletions(exc)  # type: ignore[assignment]


def test_openai_connection_error_maps_to_transport_error() -> None:
    import httpx2 as httpx
    import openai

    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    prov = OpenAIProvider(client=_RaisingOpenAIClient(exc))
    try:
        prov.parse(prompt="p", schema=_Out, system=None, model="m", max_tokens=16)
    except TransportError as caught:
        assert "OpenAI" in str(caught)
    else:
        raise AssertionError("expected TransportError")


def test_openai_non_schema_bad_request_maps_to_transport_error() -> None:
    import httpx2 as httpx
    import openai

    response = httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com"), json={})
    exc = openai.BadRequestError("invalid model", response=response, body=None)
    prov = OpenAIProvider(client=_RaisingOpenAIClient(exc))
    try:
        prov.parse(prompt="p", schema=_Out, system=None, model="m", max_tokens=16)
    except TransportError as caught:
        assert "rejected" in str(caught)
    else:
        raise AssertionError("expected TransportError")


# --- Anthropic provider maps malformed responses and transport faults the same way ---------
class _AnthropicResponse:
    def __init__(self, parsed: BaseModel | None) -> None:
        self.parsed_output = parsed
        self.usage = None
        self.model = "fake-model"


class _AnthropicMessages:
    def __init__(self, response: _AnthropicResponse | None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc

    def parse(self, **_kwargs: Any) -> _AnthropicResponse:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: _AnthropicResponse | None, exc: Exception | None = None) -> None:
        self.messages = _AnthropicMessages(response, exc)


def test_anthropic_no_parsed_output_raises_reasoner_error() -> None:
    prov = AnthropicProvider(client=_FakeAnthropicClient(_AnthropicResponse(parsed=None)))
    try:
        prov.parse(prompt="p", schema=_Out, system=None, model="m", max_tokens=16)
    except ReasonerError as exc:
        assert "no parsed output" in str(exc)
    else:
        raise AssertionError("expected ReasonerError")


def test_anthropic_happy_path_returns_data() -> None:
    prov = AnthropicProvider(client=_FakeAnthropicClient(_AnthropicResponse(parsed=_Out(x=9))))
    result = prov.parse(prompt="p", schema=_Out, system="sys", model="m", max_tokens=16)
    assert result.data.x == 9
    assert result.provider == "anthropic"


def test_anthropic_connection_error_maps_to_transport_error() -> None:
    import anthropic
    import httpx2 as httpx

    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    prov = AnthropicProvider(client=_FakeAnthropicClient(None, exc=exc))
    try:
        prov.parse(prompt="p", schema=_Out, system=None, model="m", max_tokens=16)
    except TransportError as caught:
        assert "Anthropic" in str(caught)
    else:
        raise AssertionError("expected TransportError")
