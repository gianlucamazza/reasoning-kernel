"""The central structural claim: no effect reaches a callable without passing the Verifier.

Two halves: (1) when the gate denies, the tool callable never runs; (2) in any real run, every
committed effect is preceded by an allowed gate decision for the same tool — witnessed in the trace.
"""

from __future__ import annotations

from conftest import DenyAll, ctx, tainted
from pydantic import BaseModel

from reasoning_kernel.demo.email_exfil import CLEAN_BODY, benign_plan, make_world, run_scenario
from reasoning_kernel.kernel.effects import EffectBlocked, EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.schemas.capability import Capability, CapabilitySet, EffectLevel
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.trace import EffectCommitted, GateDecision
from reasoning_kernel.tools.registry import ToolRegistry

CAP_DANGER = Capability(name="danger")


class BoomIn(BaseModel):
    x: str = "ok"


class BoomOut(BaseModel):
    pass


def _dispatcher_with(grant: CapabilitySet, declass, sentinel: dict[str, bool]) -> EffectDispatcher:
    def boom(_inp: BaseModel) -> BaseModel:
        sentinel["fired"] = True
        return BoomOut()

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="boom",
            input_schema=BoomIn,
            output_schema=BoomOut,
            required_caps=frozenset({CAP_DANGER}),
            effect_level=EffectLevel.WRITE,
        ),
        boom,
    )
    c = ctx()
    return EffectDispatcher(registry, Gate(grant, declass), TraceWriter(RunId("r")), c)


def test_capability_denied_never_runs_callable() -> None:
    sentinel = {"fired": False}
    dispatcher = _dispatcher_with(CapabilitySet(granted=frozenset()), DenyAll(), sentinel)
    try:
        dispatcher.dispatch("boom", {})
        raise AssertionError("expected EffectBlocked")
    except EffectBlocked:
        pass
    assert sentinel["fired"] is False


def test_provenance_denied_never_runs_callable() -> None:
    sentinel = {"fired": False}
    dispatcher = _dispatcher_with(
        CapabilitySet(granted=frozenset({CAP_DANGER})), DenyAll(), sentinel
    )
    try:
        dispatcher.dispatch("boom", {"x": tainted("leak")})
        raise AssertionError("expected EffectBlocked")
    except EffectBlocked:
        pass
    assert sentinel["fired"] is False


def test_every_committed_effect_was_gated_first() -> None:
    world = make_world(CLEAN_BODY)
    trace = run_scenario(
        run_id="r",
        query="summarize and send to me",
        world=world,
        plan=benign_plan(RunId("r")),
        summary_text="ok",
    )
    allowed_before: list[str] = []
    for e in trace.events:
        if isinstance(e, GateDecision) and e.verdict.allowed:
            allowed_before.append(e.tool)
        if isinstance(e, EffectCommitted):
            # the matching allowed gate decision must already have been seen
            assert e.tool in allowed_before, f"{e.tool} committed without a prior allowed gate"
