"""The Conductor walks the plan in order, commits at the end, and fails closed on bad plans."""

from __future__ import annotations

from reasoning_kernel.demo.email_exfil import CLEAN_BODY, USER_EMAIL, benign_plan, make_world
from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.store import ValueStore
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.fake import FakeProvider, Response
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import (
    ArgRef,
    ConstStep,
    Plan,
    QuarantineParseStep,
    ToolCallStep,
)
from reasoning_kernel.schemas.policy import RunContext
from reasoning_kernel.schemas.trace import (
    EffectCommitted,
    PlanEmitted,
    PlanRejected,
    QParseResult,
    RunCommitted,
    RunErrored,
    StepStarted,
)
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    MailWorld,
    RecipientIsUserPolicy,
    build_registry,
)


def _run(responses: dict[str, Response], world: MailWorld):
    ctx = RunContext(run_id=RunId("r"), user=USER_EMAIL, query="summarize and send to me")
    provider = FakeProvider(responses)
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace, ctx
    )
    interpreter = Interpreter(
        planner=PLLM(provider),
        quarantine=QLLM(provider),
        dispatcher=dispatcher,
        store=ValueStore(),
        trace=trace,
        q_schemas=Q_SCHEMAS,
    )
    return interpreter.run(ctx)


def _ok_responses() -> dict[str, Response]:
    return {"Plan": benign_plan(RunId("r")), "EmailSummary": EmailSummary(text="ok")}


def test_run_emits_plan_first_and_commit_last() -> None:
    trace = _run(_ok_responses(), make_world(CLEAN_BODY))
    assert isinstance(trace.events[0], PlanEmitted)
    assert isinstance(trace.events[-1], RunCommitted)


def test_each_step_is_started_and_quarantine_recorded() -> None:
    trace = _run(_ok_responses(), make_world(CLEAN_BODY))
    started = [e for e in trace.events if isinstance(e, StepStarted)]
    assert len(started) == 4  # const, read_inbox, q_parse, send
    assert any(isinstance(e, QParseResult) for e in trace.events)


def test_seq_is_monotonic() -> None:
    trace = _run(_ok_responses(), make_world(CLEAN_BODY))
    seqs = [e.seq for e in trace.events]
    assert seqs == list(range(len(seqs)))


# --- fail-closed (P2) --------------------------------------------------------------
def test_unknown_schema_ref_fails_closed() -> None:
    plan = Plan(
        run_id=RunId("r"),
        steps=[
            ToolCallStep(id=StepId("inbox"), tool="read_inbox", args={}),
            QuarantineParseStep(
                id=StepId("s"),
                source=ArgRef(ref=StepId("inbox")),
                schema_ref="DoesNotExist",
                instruction="x",
            ),
        ],
        final=StepId("s"),
    )
    world = make_world(CLEAN_BODY)
    trace = _run({"Plan": plan, "EmailSummary": EmailSummary(text="ok")}, world)
    assert any(isinstance(e, RunErrored) for e in trace.events)
    assert not any(isinstance(e, RunCommitted) for e in trace.events)
    assert world.sent == []


def test_invalid_path_fails_closed() -> None:
    plan = Plan(
        run_id=RunId("r"),
        steps=[
            ToolCallStep(id=StepId("inbox"), tool="read_inbox", args={}),
            QuarantineParseStep(
                id=StepId("sum"),
                source=ArgRef(ref=StepId("inbox")),
                schema_ref="EmailSummary",
                instruction="x",
            ),
            ConstStep(id=StepId("me"), value=USER_EMAIL),
            ToolCallStep(
                id=StepId("send"),
                tool="send_email",
                args={
                    "to": ArgRef(ref=StepId("me")),
                    "body": ArgRef(ref=StepId("sum"), path="nonexistent"),
                },
            ),
        ],
        final=StepId("send"),
    )
    world = make_world(CLEAN_BODY)
    trace = _run({"Plan": plan, "EmailSummary": EmailSummary(text="ok")}, world)
    assert any(isinstance(e, RunErrored) for e in trace.events)
    assert not any(isinstance(e, EffectCommitted) and e.tool == "send_email" for e in trace.events)
    assert world.sent == []


def test_invalid_plan_is_rejected_closed() -> None:
    def planner_emits_invalid(_prompt: str) -> Plan:
        # Forward reference -> Plan's validator raises at construction; surfaces as PlanRejected.
        return Plan(
            run_id=RunId("r"),
            steps=[
                ToolCallStep(
                    id=StepId("a"), tool="read_inbox", args={"x": ArgRef(ref=StepId("later"))}
                ),
                ConstStep(id=StepId("later"), value=1),
            ],
            final=StepId("a"),
        )

    world = make_world(CLEAN_BODY)
    trace = _run({"Plan": planner_emits_invalid}, world)
    assert any(isinstance(e, PlanRejected) for e in trace.events)
    assert not any(isinstance(e, RunCommitted) for e in trace.events)
    assert world.sent == []
