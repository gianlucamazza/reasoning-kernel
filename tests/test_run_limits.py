"""RunLimits: a run exceeding a bound aborts closed (no further effect committed)."""

from __future__ import annotations

from reasoning_kernel.demo.email_exfil import CLEAN_BODY, USER_EMAIL, benign_plan, make_world
from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import EffectCommitted, RunAborted, RunCommitted
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    MailWorld,
    RecipientIsUserPolicy,
    build_registry,
)


def _run(world: MailWorld, limits: RunLimits):
    # benign_plan = [const, read_inbox, q_parse, send_email] -> 4 steps, 2 effects, 1 q_parse.
    ctx = RunContext(run_id=RunId("r"), user=USER_EMAIL, query=TrustedQuery(text="x"))
    provider = FakeProvider(
        {"Plan": benign_plan(RunId("r")), "EmailSummary": EmailSummary(text="ok")}
    )
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace, ctx
    )
    return Interpreter(
        planner=PLLM(provider, grant=DEMO_GRANT),
        quarantine=QLLM(provider),
        dispatcher=dispatcher,
        trace=trace,
        q_schemas=Q_SCHEMAS,
        limits=limits,
    ).run(ctx)


def test_max_effects_aborts_before_second_effect() -> None:
    world = make_world(CLEAN_BODY)
    trace = _run(world, RunLimits(max_effects=1))
    assert any(isinstance(e, RunAborted) for e in trace.events)
    assert sum(isinstance(e, EffectCommitted) for e in trace.events) == 1  # read_inbox only
    assert world.sent == []
    assert not any(isinstance(e, RunCommitted) for e in trace.events)


def test_max_steps_aborts_before_running() -> None:
    world = make_world(CLEAN_BODY)
    trace = _run(world, RunLimits(max_steps=2))  # plan has 4 steps
    assert any(isinstance(e, RunAborted) for e in trace.events)
    assert not any(isinstance(e, EffectCommitted) for e in trace.events)
    assert world.sent == []


def test_max_q_parses_aborts() -> None:
    world = make_world(CLEAN_BODY)
    trace = _run(world, RunLimits(max_q_parses=0))  # plan has 1 q_parse
    assert any(isinstance(e, RunAborted) for e in trace.events)
    assert world.sent == []


def test_default_limits_are_unbounded() -> None:
    world = make_world(CLEAN_BODY)
    trace = _run(world, RunLimits())
    assert any(isinstance(e, RunCommitted) for e in trace.events)
    assert world.sent and world.sent[0].to == USER_EMAIL
