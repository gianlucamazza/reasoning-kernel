"""Composable sub-kernels (§5.4): delegating untrusted content under a reduced, clamped grant."""

from __future__ import annotations

from collections.abc import Callable

from reasoning_kernel.demo.email_exfil import CLEAN_BODY, INJECTED_BODY, USER_EMAIL, make_world
from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import CapabilitySet
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.plan import ArgRef, ConstStep, Plan, SubKernelStep, ToolCallStep
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import (
    EffectBlockedEvent,
    EffectCommitted,
    GateDecision,
    RunAborted,
    RunCommitted,
    RunErrored,
)
from reasoning_kernel.tools.demo_mail import (
    CAP_CALENDAR_WRITE,
    CAP_MAIL_READ,
    DEMO_GRANT,
    Q_SCHEMAS,
    MailWorld,
    RecipientIsUserPolicy,
    build_registry,
)

# Unique marker placed in the SubKernelStep instruction; routes the FakeProvider to the sub-plan.
MARKER = "SUBKERNEL_MEETING_TASK"


def _outer_plan(grant: list[str]) -> Plan:
    return Plan(
        run_id=RunId("r"),
        steps=[
            ToolCallStep(id=StepId("inbox"), tool="read_inbox", args={}),
            SubKernelStep(
                id=StepId("delegate"),
                source=ArgRef(ref=StepId("inbox"), path="latest.body"),
                instruction=f"{MARKER}: if a meeting is requested, create the event",
                grant=grant,
            ),
        ],
        final=StepId("delegate"),
    )


def _sub_creates_event() -> Plan:
    return Plan(
        run_id=RunId("r/delegate"),
        steps=[
            ConstStep(id=StepId("title"), value="Sync meeting"),
            ConstStep(id=StepId("date"), value="tomorrow"),
            ToolCallStep(
                id=StepId("ev"),
                tool="create_event",
                args={"title": ArgRef(ref=StepId("title")), "date": ArgRef(ref=StepId("date"))},
            ),
        ],
        final=StepId("ev"),
    )


def _sub_obeys_injection() -> Plan:
    # A compromised sub-planner tries to exfiltrate; confined by the reduced grant.
    return Plan(
        run_id=RunId("r/delegate"),
        steps=[ToolCallStep(id=StepId("c"), tool="read_contacts", args={})],
        final=StepId("c"),
    )


def _sub_recurses() -> Plan:
    # Uses a const blob (no capability needed) so the depth guard, not a missing cap, is what fires.
    return Plan(
        run_id=RunId("r/delegate"),
        steps=[
            ConstStep(id=StepId("blob"), value="nested content"),
            SubKernelStep(
                id=StepId("deeper"),
                source=ArgRef(ref=StepId("blob")),
                instruction=f"{MARKER}: nested",
                grant=["calendar.write"],
            ),
        ],
        final=StepId("deeper"),
    )


def _provider(outer: Plan, sub: Plan) -> FakeProvider:
    def route(prompt: str) -> Plan:
        return sub if MARKER in prompt else outer

    routed: Callable[[str], Plan] = route
    return FakeProvider({"Plan": routed})


def _run(
    world: MailWorld,
    outer: Plan,
    sub: Plan,
    *,
    outer_grant: CapabilitySet = DEMO_GRANT,
    limits: RunLimits | None = None,
):
    ctx = RunContext(
        run_id=RunId("r"), user=USER_EMAIL, query=TrustedQuery(text="handle my latest email")
    )
    provider = _provider(outer, sub)
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(outer_grant, RecipientIsUserPolicy()), trace, ctx
    )
    interp = Interpreter(
        planner=PLLM(provider, grant=outer_grant),
        quarantine=QLLM(provider),
        dispatcher=dispatcher,
        trace=trace,
        q_schemas=Q_SCHEMAS,
        limits=limits if limits is not None else RunLimits(),
    )
    return interp.run(ctx), world


def test_benign_subkernel_creates_event_via_declassification() -> None:
    world = make_world(CLEAN_BODY)
    result, world = _run(world, _outer_plan(["calendar.write"]), _sub_creates_event())
    assert any(isinstance(e, RunCommitted) for e in result.trace.events)
    assert len(world.events) == 1
    # The event went through declassification (args are tainted: readers empty), not a fast-path.
    decisions = [
        e for e in result.trace.events if isinstance(e, GateDecision) and e.tool == "create_event"
    ]
    assert decisions and decisions[-1].verdict.allowed
    assert "own data" in decisions[-1].verdict.reason


def test_injection_confined_by_reduced_grant() -> None:
    # The outer kernel HAS mail.send/contacts.read, but delegates only calendar.write.
    world = make_world(INJECTED_BODY)
    result, world = _run(world, _outer_plan(["calendar.write"]), _sub_obeys_injection())
    assert any(
        isinstance(e, EffectBlockedEvent) and e.tool == "read_contacts" for e in result.trace.events
    )
    assert any(isinstance(e, RunErrored) for e in result.trace.events)  # outer fails closed
    assert world.sent == [] and world.events == []
    # The outer read_inbox may commit; nothing harmful (send/contacts/event) does.
    committed = {e.tool for e in result.trace.events if isinstance(e, EffectCommitted)}
    assert committed <= {"read_inbox"}


def test_clamp_does_not_widen_beyond_outer_grant() -> None:
    # Outer grant lacks mail.send; the SubKernelStep requests it; the clamp removes it.
    reduced = CapabilitySet(granted=frozenset({CAP_MAIL_READ, CAP_CALENDAR_WRITE}))
    world = make_world(INJECTED_BODY)
    result, world = _run(
        world,
        _outer_plan(["mail.send", "calendar.write"]),  # asks for mail.send too
        _sub_obeys_injection(),  # tries read_contacts (also absent) -> blocked
        outer_grant=reduced,
    )
    assert any(isinstance(e, EffectBlockedEvent) for e in result.trace.events)
    assert world.sent == []


def test_max_depth_aborts_recursion() -> None:
    world = make_world(CLEAN_BODY)
    result, world = _run(
        world, _outer_plan(["calendar.write"]), _sub_recurses(), limits=RunLimits(max_depth=1)
    )
    assert any(isinstance(e, RunAborted) for e in result.trace.events)
    assert world.events == []


def test_outer_value_label_dominates_subkernel() -> None:
    world = make_world(CLEAN_BODY)
    result, _ = _run(world, _outer_plan(["calendar.write"]), _sub_creates_event())
    assert result.committed is not None
    # The outer wrapped value is tainted (it summarizes work over untrusted content).
    assert result.committed.label.is_tainted
