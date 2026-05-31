"""MergeStep combines results into one value, joining their labels (taint only increases)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import (
    ArgRef,
    ConstStep,
    MergeStep,
    Plan,
    QuarantineParseStep,
    ToolCallStep,
)
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.provenance import Source
from reasoning_kernel.schemas.trace import RunResult
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    Contact,
    EmailMessage,
    EmailSummary,
    MailWorld,
    RecipientIsUserPolicy,
    build_registry,
)

USER = "user@example.com"


def _sid(s: str) -> StepId:
    return StepId(s)


def _world() -> MailWorld:
    return MailWorld(
        inbox=[EmailMessage(sender="boss@example.com", subject="Hi", body="3pm meeting")],
        contacts=[Contact(name="Alice", email="alice@example.com")],
    )


def _run(world: MailWorld, plan: Plan, summary: str = "ok") -> RunResult:
    ctx = RunContext(run_id=RunId("merge-test"), user=USER, query=TrustedQuery(text="q"))
    provider = FakeProvider({"Plan": plan, "EmailSummary": EmailSummary(text=summary)})
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace, ctx
    )
    interp = Interpreter(
        planner=PLLM(provider, grant=DEMO_GRANT),
        quarantine=QLLM(provider),
        dispatcher=dispatcher,
        trace=trace,
        q_schemas=Q_SCHEMAS,
    )
    return interp.run(ctx)


def test_merge_requires_inputs() -> None:
    with pytest.raises(ValidationError, match="no inputs"):
        MergeStep(id=_sid("m"), inputs={})


def test_merge_refs_are_forward_only() -> None:
    with pytest.raises(ValidationError):
        Plan(
            run_id=RunId("r"),
            steps=[
                MergeStep(id=_sid("m"), inputs={"x": ArgRef(ref=_sid("later"))}),
                ConstStep(id=_sid("later"), value=1),
            ],
            final=_sid("m"),
        )


def test_merge_joins_labels_of_its_inputs() -> None:
    plan = Plan(
        run_id=RunId("merge-test"),
        steps=[
            ToolCallStep(id=_sid("inbox"), tool="read_inbox", args={}),
            ToolCallStep(id=_sid("contacts"), tool="read_contacts", args={}),
            MergeStep(
                id=_sid("m"),
                inputs={
                    "email": ArgRef(ref=_sid("inbox"), path="latest.body"),
                    "contacts": ArgRef(ref=_sid("contacts")),
                },
            ),
        ],
        final=_sid("m"),
    )
    result = _run(_world(), plan)
    assert result.committed is not None
    label = result.committed.label
    assert Source.DERIVED in label.sources  # combined > 1 input
    assert Source.TOOL_READ in label.sources  # both inputs came from READ tools
    assert label.has_third_party  # contacts are third-party → subjects union
    assert label.readers == frozenset()  # readers intersection of two blocked reads
    value = result.committed.value
    assert isinstance(value, dict)
    assert set(value.keys()) == {"email", "contacts"}  # a dict of the named inputs


def test_merge_propagates_taint_so_a_later_send_is_blocked() -> None:
    plan = Plan(
        run_id=RunId("merge-test"),
        steps=[
            ConstStep(id=_sid("me"), value=USER),
            ToolCallStep(id=_sid("inbox"), tool="read_inbox", args={}),
            ToolCallStep(id=_sid("contacts"), tool="read_contacts", args={}),
            MergeStep(
                id=_sid("m"),
                inputs={
                    "email": ArgRef(ref=_sid("inbox"), path="latest.body"),
                    "contacts": ArgRef(ref=_sid("contacts")),
                },
            ),
            QuarantineParseStep(
                id=_sid("sum"),
                source=ArgRef(ref=_sid("m")),
                schema_ref="EmailSummary",
                instruction="Summarize the email and the contacts.",
            ),
            ToolCallStep(
                id=_sid("send"),
                tool="send_email",
                args={
                    "to": ArgRef(ref=_sid("me")),
                    "body": ArgRef(ref=_sid("sum"), path="text"),
                },
            ),
        ],
        final=_sid("send"),
    )
    world = _world()
    result = _run(world, plan)
    assert result.committed is None  # run failed closed
    assert world.sent == []  # the third-party-tainted summary never left
