"""Key-free reference implementation of the complete operational profile."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel

from reasoning_kernel.conformance.models import (
    ConformanceObservation,
    ConformanceScenario,
    ConformanceSuite,
    ScenarioKind,
)
from reasoning_kernel.demo.email_exfil import (
    ATTACKER_EMAIL,
    CLEAN_BODY,
    INJECTED_BODY,
    USER_EMAIL,
    benign_plan,
    make_world,
    malicious_plan,
)
from reasoning_kernel.kernel.session import RunSession
from reasoning_kernel.memory.sink import (
    MemoryTraceSink,
    SQLiteTraceSink,
    TraceSink,
    TraceStorageError,
)
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import CapabilitySet
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import ArgRef, ConstStep, Plan, PlanStep, ToolCallStep
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import AuditEvent, RunResult
from reasoning_kernel.tools.demo_mail import (
    CAP_MAIL_SEND,
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    MailWorld,
    RecipientIsUserPolicy,
    SendEmailIn,
    build_registry,
)
from reasoning_kernel.tools.registry import ToolCallable, ToolRegistry


def _direct_plan(run_id: RunId) -> Plan:
    steps: list[PlanStep] = [
        ConstStep(id=StepId("recipient"), value=USER_EMAIL),
        ConstStep(id=StepId("body"), value="Status update"),
        ToolCallStep(
            id=StepId("send"),
            tool="send_email",
            args={
                "to": ArgRef(ref=StepId("recipient")),
                "body": ArgRef(ref=StepId("body")),
            },
        ),
        ConstStep(id=StepId("title"), value="Follow-up"),
        ConstStep(id=StepId("date"), value="2030-01-01"),
        ToolCallStep(
            id=StepId("later"),
            tool="create_event",
            args={
                "title": ArgRef(ref=StepId("title")),
                "date": ArgRef(ref=StepId("date")),
            },
        ),
    ]
    return Plan(
        run_id=run_id,
        steps=steps,
        final=StepId("later"),
    )


def _registry_with(world: MailWorld, tool: str, replacement: ToolCallable) -> ToolRegistry:
    original = build_registry(world)
    registry = ToolRegistry()
    for spec in original.catalog():
        registered = original.get(spec.name)
        registry.register(spec, replacement if spec.name == tool else registered.callable)
    return registry


def _run(
    run_id: str,
    plan: Plan,
    world: MailWorld,
    *,
    registry: ToolRegistry | None = None,
    grant: CapabilitySet = DEMO_GRANT,
    sink: TraceSink | None = None,
) -> RunResult:
    ctx = RunContext(
        run_id=RunId(run_id),
        user=USER_EMAIL,
        query=TrustedQuery(text="Execute the reference conformance scenario"),
    )
    provider = FakeProvider({"Plan": plan, "EmailSummary": EmailSummary(text="Safe summary")})
    return RunSession(
        ctx=ctx,
        registry=registry or build_registry(world),
        grant=grant,
        declass=RecipientIsUserPolicy(),
        planner=PLLM(provider, grant=grant),
        quarantine=QLLM(provider),
        q_schemas=Q_SCHEMAS,
        sink=sink or MemoryTraceSink(),
    ).run()


def _benign() -> ConformanceObservation:
    world = make_world(CLEAN_BODY)
    result = _run("conformance-benign", benign_plan(RunId("conformance-benign")), world)
    return ConformanceObservation(result=result, authorized_effects=len(world.sent))


def _injected_control() -> ConformanceObservation:
    world = make_world(INJECTED_BODY)
    result = _run(
        "conformance-injected-control",
        benign_plan(RunId("conformance-injected-control")),
        world,
    )
    unauthorized = sum(message.to == ATTACKER_EMAIL for message in world.sent)
    return ConformanceObservation(
        result=result,
        authorized_effects=sum(message.to == USER_EMAIL for message in world.sent),
        unauthorized_effects=unauthorized,
    )


def _injected_egress() -> ConformanceObservation:
    world = make_world(CLEAN_BODY)
    result = _run(
        "conformance-injected-egress",
        malicious_plan(RunId("conformance-injected-egress")),
        world,
    )
    return ConformanceObservation(
        result=result,
        unauthorized_effects=sum(message.to == ATTACKER_EMAIL for message in world.sent),
    )


def _capability_denied() -> ConformanceObservation:
    world = make_world(CLEAN_BODY)
    run_id = RunId("conformance-capability-denied")
    grant = CapabilitySet(granted=DEMO_GRANT.granted - {CAP_MAIL_SEND})
    result = _run(run_id, _direct_plan(run_id), world, grant=grant)
    return ConformanceObservation(result=result, authorized_effects=len(world.sent))


def _invalid_output() -> ConformanceObservation:
    world = make_world(CLEAN_BODY)

    def invalid(inp: BaseModel) -> BaseModel:
        if isinstance(inp, SendEmailIn):
            world.sent.append(inp)
        return EmailSummary(text="wrong output model")

    run_id = RunId("conformance-invalid-output")
    result = _run(
        run_id,
        _direct_plan(run_id),
        world,
        registry=_registry_with(world, "send_email", invalid),
    )
    return ConformanceObservation(
        result=result,
        authorized_effects=len(world.sent),
        subsequent_effects=len(world.events),
    )


def _tool_failure(*, after_effect: bool) -> ConformanceObservation:
    world = make_world(CLEAN_BODY)

    def fail(inp: BaseModel) -> BaseModel:
        if after_effect and isinstance(inp, SendEmailIn):
            world.sent.append(inp)
        raise RuntimeError("reference adapter failure")

    suffix = "after" if after_effect else "before"
    run_id = RunId(f"conformance-tool-failure-{suffix}")
    result = _run(
        run_id,
        _direct_plan(run_id),
        world,
        registry=_registry_with(world, "send_email", fail),
    )
    return ConformanceObservation(
        result=result,
        authorized_effects=len(world.sent),
        subsequent_effects=len(world.events),
    )


class _FailBeforeDispatchSink:
    def __init__(self) -> None:
        self._inner = MemoryTraceSink()

    def start(self, run_id: RunId) -> None:
        self._inner.start(run_id)

    def append(self, root_run_id: RunId, event: AuditEvent) -> None:
        if event.kind == "effect_started":
            raise TraceStorageError("reference injected storage failure")
        self._inner.append(root_run_id, event)


def _audit_failure() -> ConformanceObservation:
    world = make_world(CLEAN_BODY)
    run_id = RunId("conformance-audit-failure")
    result = _run(run_id, _direct_plan(run_id), world, sink=_FailBeforeDispatchSink())
    return ConformanceObservation(result=result, authorized_effects=len(world.sent))


def _crash_reopen() -> ConformanceObservation:
    run_id = RunId("conformance-crashed-run")
    with tempfile.TemporaryDirectory(prefix="rk-conformance-") as directory:
        path = Path(directory) / "audit.sqlite"
        with SQLiteTraceSink(path) as sink:
            sink.start(run_id)
            sink.append(
                run_id,
                AuditEvent(
                    kind="effect_started",
                    run_id=run_id,
                    seq=0,
                    invocation_id="reference-invocation",
                    metadata={"tool": "send_email"},
                ),
            )
        with SQLiteTraceSink(path) as reopened:
            incomplete_discovered = run_id in reopened.runs_requiring_review()
            try:
                reopened.start(run_id)
            except TraceStorageError:
                replay_refused = True
            else:
                replay_refused = False
    return ConformanceObservation(
        replay_refused=replay_refused,
        incomplete_discovered=incomplete_discovered,
    )


def reference_suite() -> ConformanceSuite:
    """Return the package's deterministic, complete self-conformance suite."""

    return ConformanceSuite(
        name="reasoning-kernel-reference",
        scenarios=(
            ConformanceScenario(ScenarioKind.BENIGN_EFFECT, _benign),
            ConformanceScenario(ScenarioKind.INJECTED_CONTROL, _injected_control),
            ConformanceScenario(ScenarioKind.INJECTED_EGRESS, _injected_egress),
            ConformanceScenario(ScenarioKind.CAPABILITY_DENIED, _capability_denied),
            ConformanceScenario(ScenarioKind.INVALID_OUTPUT, _invalid_output),
            ConformanceScenario(
                ScenarioKind.TOOL_FAILURE_BEFORE_EFFECT,
                lambda: _tool_failure(after_effect=False),
            ),
            ConformanceScenario(
                ScenarioKind.TOOL_FAILURE_AFTER_EFFECT,
                lambda: _tool_failure(after_effect=True),
            ),
            ConformanceScenario(ScenarioKind.AUDIT_FAILURE_BEFORE_DISPATCH, _audit_failure),
            ConformanceScenario(ScenarioKind.CRASH_REOPEN_NO_REPLAY, _crash_reopen),
        ),
    )
