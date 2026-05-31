"""Composable strong form (§5.4): a reasoner can never exceed the outer capability grant."""

from __future__ import annotations

import pytest

from reasoning_kernel.demo.email_exfil import CLEAN_BODY, USER_EMAIL, benign_plan, make_world
from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import Capability, CapabilitySet
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import RunCommitted
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    RecipientIsUserPolicy,
    build_registry,
)


def _build(planner_grant: CapabilitySet):
    world = make_world(CLEAN_BODY)
    ctx = RunContext(run_id=RunId("r"), user=USER_EMAIL, query=TrustedQuery(text="x"))
    provider = FakeProvider(
        {"Plan": benign_plan(RunId("r")), "EmailSummary": EmailSummary(text="ok")}
    )
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace, ctx
    )
    interp = Interpreter(
        planner=PLLM(provider, grant=planner_grant),
        quarantine=QLLM(provider),
        dispatcher=dispatcher,
        trace=trace,
        q_schemas=Q_SCHEMAS,
    )
    return interp, ctx, world


def test_planner_grant_exceeding_dispatcher_is_rejected() -> None:
    too_much = CapabilitySet(granted=DEMO_GRANT.granted | {Capability(name="fs.write")})
    with pytest.raises(ValueError, match="exceeds"):
        _build(too_much)


def test_subset_grant_accepted_and_commits() -> None:
    interp, ctx, world = _build(DEMO_GRANT)
    trace = interp.run(ctx).trace
    assert any(isinstance(e, RunCommitted) for e in trace.events)
    assert world.sent and world.sent[0].to == USER_EMAIL


def test_quarantine_holds_no_capability() -> None:
    assert QLLM(FakeProvider({})).grant.granted == frozenset()
