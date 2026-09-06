"""Operational contracts: authority, partial effects, durable audit and independent sessions."""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from conftest import DenyAll, tainted, trusted
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from reasoning_kernel import (
    PLLM,
    QLLM,
    ArgRef,
    Capability,
    CapabilitySet,
    ConstStep,
    EffectDispatcher,
    EffectLevel,
    FakeProvider,
    Gate,
    Interpreter,
    MemoryTraceSink,
    Plan,
    QuarantineParseStep,
    RunContext,
    RunId,
    RunLimits,
    RunSession,
    SQLiteTraceSink,
    StepId,
    SubKernelStep,
    ToolCallStep,
    ToolRegistry,
    ToolSpec,
    TraceStorageError,
    TraceWriter,
    TrustedQuery,
    VerifierVerdict,
)
from reasoning_kernel.kernel.runtime import ReasonerExecutor, RunBoundExceeded
from reasoning_kernel.schemas.trace import AuditEvent, EffectStarted, RunBlocked, digest

CAP = Capability("write")
GRANT = CapabilitySet(granted=frozenset({CAP}))


class Input(BaseModel):
    text: str = "default"


class Output(BaseModel):
    ok: bool = True


def context(run_id="test"):
    return RunContext(run_id=RunId(run_id), user="user", query=TrustedQuery(text="secret-query"))


def registry_for(fn, *, boundary=True, effect=EffectLevel.WRITE, schema=Input):
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="write",
            input_schema=schema,
            output_schema=Output,
            required_caps=frozenset({CAP}),
            effect_level=effect,
            args_leave_boundary=boundary,
        ),
        fn,
    )
    return registry


def plan_for(*steps):
    return Plan(run_id=RunId("test"), steps=list(steps), final=steps[-1].id)


def write_step(step_id="write"):
    return ToolCallStep(id=StepId(step_id), tool="write", args={"text": "secret-payload"})


def session(registry, *, plan=None, provider=None, sink=None, ctx=None, limits=None):
    provider = provider or FakeProvider({"Plan": plan or plan_for(write_step())})
    return RunSession(
        ctx=ctx or context(),
        registry=registry,
        grant=GRANT,
        declass=DenyAll(),
        planner=PLLM(provider, grant=GRANT),
        quarantine=QLLM(provider),
        q_schemas={},
        sink=sink if sink is not None else MemoryTraceSink(),
        limits=limits,
    )


def test_session_reuse_and_incomplete_contract_rejected():
    calls = []
    registry = registry_for(lambda inp: calls.append(inp) or Output())
    run = session(registry)
    assert run.run().status == "succeeded"
    with pytest.raises(ValueError, match="single-use"):
        run.run()
    assert len(calls) == 1
    with pytest.raises(ValueError, match="args_leave_boundary"):
        session(registry_for(lambda _: Output(), boundary=None))


def test_context_and_trace_mismatch_precedes_provider_call():
    ctx = context()
    trace = TraceWriter(ctx.run_id)
    provider = FakeProvider({})  # invocation would fail: no script
    kernel = Interpreter(
        planner=PLLM(provider, grant=GRANT),
        quarantine=QLLM(provider),
        dispatcher=EffectDispatcher(
            registry_for(lambda _: Output()), Gate(GRANT, DenyAll()), trace, ctx
        ),
        trace=trace,
        q_schemas={},
    )
    with pytest.raises(ValueError, match="context"):
        kernel.run(context("other"))
    assert trace.snapshot().events == []


def test_gate_receives_normalized_input_once_and_tool_receives_same_value():
    validations, policy_values, calls = [], [], []

    class Normalized(Input):
        @field_validator("text")
        @classmethod
        def normalize(cls, text):
            validations.append(text)
            return text.strip()

    class Policy:
        def may_declassify(self, spec, args, ctx):
            policy_values.append(args["text"].value)
            return VerifierVerdict(allowed=args["text"].value == "safe", reason="checked")

    ctx = context()
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        registry_for(lambda inp: calls.append(inp.text) or Output(), schema=Normalized),
        Gate(GRANT, Policy()),
        trace,
        ctx,
    )
    dispatcher.dispatch("write", {"text": tainted(" safe ")})
    assert validations == [" safe "]
    assert policy_values == calls == ["safe"]


def test_egress_read_is_gated_and_grant_cannot_widen():
    calls = []
    spec = registry_for(
        lambda _: calls.append(True) or Output(), effect=EffectLevel.READ
    ).catalog()[0]
    gate = Gate(GRANT, DenyAll())
    assert not gate.check(spec, {"text": tainted("secret")}, context()).allowed
    empty = Gate(CapabilitySet(granted=frozenset()), DenyAll())
    assert empty.for_grant(GRANT).grant.granted == frozenset()
    assert not calls


@pytest.mark.parametrize("failure", ["raises", "invalid"])
def test_partial_effect_is_explicit_and_no_next_tool_runs(failure):
    calls = []

    def tool(inp):
        calls.append(inp)
        if failure == "raises":
            raise RuntimeError("secret-exception")
        return Input(text="secret-output")

    result = session(registry_for(tool), plan=plan_for(write_step("a"), write_step("b"))).run()
    assert result.status == "errored" and result.committed is None
    assert len(calls) == len(result.effects) == 1
    assert result.effects[0].status == ("uncertain" if failure == "raises" else "completed")
    if failure == "invalid":
        assert result.effects[0].output_valid is False
    assert "secret" not in result.trace.model_dump_json()


def test_repeated_tool_calls_have_distinct_authorizations():
    result = session(
        registry_for(lambda _: Output()), plan=plan_for(write_step("a"), write_step("b"))
    ).run()
    assert result.status == "succeeded"
    allowed = set()
    starts = set()
    for event in result.trace.events:
        if event.kind == "gate_decision" and event.metadata["allowed"]:
            allowed.add(event.invocation_id)
        elif event.kind == "effect_started":
            assert event.invocation_id in allowed
            starts.add(event.invocation_id)
        elif event.kind == "effect_committed":
            assert event.invocation_id in starts
            starts.remove(event.invocation_id)
    assert len(allowed) == len(result.effects) == 2 and not starts


def test_snapshot_and_emitted_objects_are_detached():
    writer = TraceWriter(RunId("r"))
    event = RunBlocked(run_id=RunId("r"), tool="original")
    writer.emit(event)
    event.tool = "changed"
    snapshot = writer.snapshot()
    snapshot.events[0].tool = "also changed"
    assert writer.snapshot().events[0].tool == "original"
    assert digest({"a": 1, "b": {3, 2}}) == digest({"b": {2, 3}, "a": 1})
    with pytest.raises(ValueError):
        digest(object())


def test_sqlite_reopen_preserves_uncertain_invocation_and_refuses_replay(tmp_path):
    path = tmp_path / "audit.sqlite"
    with SQLiteTraceSink(path) as sink:
        writer = TraceWriter(RunId("crashed"), sink=sink, operational=True)
        writer.emit(EffectStarted(run_id=RunId("crashed"), tool="write", invocation_id="call"))
    with SQLiteTraceSink(path) as sink:
        events = sink.read(RunId("crashed"))
        assert [e.kind for e in events] == ["effect_started"]
        with pytest.raises(TraceStorageError):
            session(registry_for(lambda _: Output()), ctx=context("crashed"), sink=sink)


@pytest.mark.parametrize(
    "kind,expected_calls,expected_effects",
    [
        ("gate_decision", 0, 0),
        ("effect_started", 0, 0),
        ("effect_committed", 1, 1),
    ],
)
def test_audit_failure_stops_at_correct_boundary(kind, expected_calls, expected_effects):
    class FailingSink(MemoryTraceSink):
        def append(self, run_id, event):
            if event.kind == kind:
                raise OSError("secret-disk-error")
            super().append(run_id, event)

    calls = []
    sink = FailingSink()
    result = session(
        registry_for(lambda _: calls.append(True) or Output()),
        sink=sink,
        plan=plan_for(write_step("a"), write_step("b")),
    ).run()
    assert result.status == "audit_failed"
    assert len(calls) == expected_calls and len(result.effects) == expected_effects
    assert all(e.status == "uncertain" for e in result.effects)


def test_concurrent_sessions_share_sink_without_contamination(tmp_path):
    barrier = threading.Barrier(2)

    def tool(_):
        barrier.wait(timeout=5)
        return Output()

    with SQLiteTraceSink(tmp_path / "audit.sqlite") as sink:
        sessions = [
            session(registry_for(tool), sink=sink, ctx=context(name)) for name in ("a", "b")
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda s: s.run(), sessions))
        for result, name in zip(results, ("a", "b"), strict=True):
            assert result.status == "succeeded"
            events = sink.read(RunId(name))
            assert all(e.run_id == name for e in events)
            assert [e.seq for e in events] == list(range(len(events)))
            assert "secret" not in "".join(e.model_dump_json() for e in events)


@pytest.mark.parametrize(
    "field", ["max_steps", "max_effects", "max_q_parses", "max_llm_calls", "max_depth"]
)
def test_limits_reject_negative_values(field):
    with pytest.raises(ValidationError):
        RunLimits(**{field: -1})


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_timeout_requires_finite_positive_value(timeout):
    with pytest.raises(ValidationError):
        RunLimits(reasoner_timeout_s=timeout)


def test_sibling_subkernels_share_effect_budget():
    calls = []
    outer = plan_for(
        ConstStep(id=StepId("source"), value="blob"),
        *[
            SubKernelStep(
                id=StepId(name),
                source=ArgRef(ref=StepId("source")),
                instruction="CHILD",
                grant=["write"],
            )
            for name in ("one", "two")
        ],
    )
    child = plan_for(write_step())
    provider = FakeProvider({"Plan": lambda prompt: child if "CHILD" in prompt else outer})
    result = session(
        registry_for(lambda _: calls.append(True) or Output()),
        provider=provider,
        limits=RunLimits(max_effects=1),
    ).run()
    assert result.status == "aborted" and len(calls) == 1
    assert len(result.effects) == 1
    children = [e for e in result.trace.events if e.parent_run_id]
    assert children and all(e.parent_run_id == "test" for e in children)


@pytest.mark.parametrize("limits", [RunLimits(max_steps=3), RunLimits(max_llm_calls=0)])
def test_global_budget_stops_before_effect(limits):
    calls = []
    outer = plan_for(
        ConstStep(id=StepId("source"), value="blob"),
        SubKernelStep(
            id=StepId("child"),
            source=ArgRef(ref=StepId("source")),
            instruction="CHILD",
            grant=["write"],
        ),
    )
    child = plan_for(ConstStep(id=StepId("constant"), value="x"), write_step())
    provider = FakeProvider({"Plan": lambda prompt: child if "CHILD" in prompt else outer})
    result = session(
        registry_for(lambda _: calls.append(True) or Output()), provider=provider, limits=limits
    ).run()
    assert result.status == "aborted" and not calls


def test_timed_out_call_retains_executor_slot_until_released():
    executor = ReasonerExecutor(max_workers=1)
    entered, release = threading.Event(), threading.Event()

    def hung():
        entered.set()
        release.wait(timeout=5)

    try:
        with pytest.raises(RunBoundExceeded, match="exceeded"):
            executor.call(hung, 0.05)
        assert entered.is_set()
        with pytest.raises(RunBoundExceeded, match="capacity"):
            executor.call(lambda: None, 0.05)
    finally:
        release.set()
        executor.close()


def test_catalog_is_detached_from_host_registration():
    registry = registry_for(lambda _: Output())
    provider = FakeProvider(
        {
            "Plan": lambda prompt: plan_for(
                ConstStep(id=StepId("done"), value="UNIQUE_NEW_TOOL" not in prompt)
            )
        }
    )
    run = session(registry, provider=provider)
    registry.register(
        ToolSpec(
            name="UNIQUE_NEW_TOOL",
            input_schema=Input,
            output_schema=Output,
            required_caps=frozenset({CAP}),
            effect_level=EffectLevel.WRITE,
            args_leave_boundary=True,
        ),
        lambda _: Output(),
    )
    assert run.run().committed.value is True


def test_sink_sequence_and_duplicate_run_guard(tmp_path):
    with SQLiteTraceSink(tmp_path / "audit.sqlite") as sink:
        sink.start(RunId("r"))
        with pytest.raises(TraceStorageError):
            sink.append(RunId("r"), AuditEvent(run_id=RunId("r"), seq=1))
        sink.append(RunId("r"), AuditEvent(run_id=RunId("r"), seq=0))
        assert len(sink.read(RunId("r"))) == 1


@pytest.mark.parametrize(
    "stage,called,last_kind",
    [
        ("before_tool", False, "effect_started"),
        ("inside_tool", True, "effect_started"),
        ("after_tool", True, "effect_committed"),
    ],
)
def test_process_crash_has_durable_evidence_without_replay(tmp_path, stage, called, last_kind):
    path, marker = tmp_path / "audit.sqlite", tmp_path / "external-effect"
    code = """
import os, sys
from pathlib import Path
from test_operational import session, registry_for, Output
from reasoning_kernel import SQLiteTraceSink
class CrashSink(SQLiteTraceSink):
    def append(self, root, event):
        super().append(root, event)
        if (sys.argv[3] == "before_tool" and event.kind == "effect_started" or
            sys.argv[3] == "after_tool" and event.kind == "effect_committed"):
            os._exit(31)
def tool(_):
    Path(sys.argv[2]).write_text("external effect")
    if sys.argv[3] == "inside_tool":
        os._exit(31)
    return Output()
session(registry_for(tool), sink=CrashSink(sys.argv[1])).run()
"""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(__file__).parent), str(Path(__file__).parent.parent / "src")]
        ),
    }
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), str(marker), stage],
        env=env,
        timeout=10,
        check=False,
        capture_output=True,
    )
    assert result.returncode == 31, result.stderr.decode()
    assert marker.exists() is called
    with SQLiteTraceSink(path) as sink:
        assert sink.read(RunId("test"))[-1].kind == last_kind
        with pytest.raises(TraceStorageError):
            session(registry_for(lambda _: pytest.fail("must not replay")), sink=sink)


def test_untrusted_step_id_is_not_persisted():
    result = session(
        registry_for(lambda _: Output()), plan=plan_for(write_step("secret-step"))
    ).run()
    assert result.status == "succeeded"
    assert "secret" not in result.trace.model_dump_json()
    assert result.effects[0].step_id.startswith("step-")


def test_schema_extra_fields_cannot_escape_provenance_check():
    class WithExtras(Input):
        model_config = ConfigDict(extra="allow")

    spec = registry_for(lambda _: Output(), schema=WithExtras).catalog()[0]
    checked = Gate(GRANT, DenyAll()).authorize(spec, {"hidden": tainted("secret")}, context())
    assert checked.args["hidden"].label.is_tainted
    assert not checked.verdict.allowed


def test_mutating_validator_cannot_launder_taint_or_change_store_payload():
    class MutableInput(BaseModel):
        public: list[str]
        private: list[str]

        @model_validator(mode="after")
        def combine(self):
            self.public.extend(self.private)
            self.private.clear()
            return self

    raw = {"public": trusted([]), "private": tainted(["secret"])}
    spec = registry_for(lambda _: Output(), schema=MutableInput).catalog()[0]
    checked = Gate(GRANT, DenyAll()).authorize(spec, raw, context())
    assert raw["public"].value == [] and raw["private"].value == ["secret"]
    assert checked.args["public"].label.is_tainted and not checked.verdict.allowed


def test_child_catalog_contains_only_delegated_tools():
    outer = plan_for(
        ConstStep(id=StepId("source"), value="blob"),
        SubKernelStep(
            id=StepId("child"), source=ArgRef(ref=StepId("source")), instruction="CHILD", grant=[]
        ),
    )

    def route(prompt):
        if "CHILD" in prompt:
            assert '"name": "write"' not in prompt
            return plan_for(ConstStep(id=StepId("done"), value="ok"))
        return outer

    result = session(
        registry_for(lambda _: pytest.fail("no tool call")), provider=FakeProvider({"Plan": route})
    ).run()
    assert result.status == "succeeded"


def test_sibling_q_parses_share_budget():
    outer = plan_for(
        ConstStep(id=StepId("source"), value="blob"),
        *[
            SubKernelStep(
                id=StepId(name), source=ArgRef(ref=StepId("source")), instruction="CHILD", grant=[]
            )
            for name in ("a", "b")
        ],
    )
    child = plan_for(
        ConstStep(id=StepId("source"), value="blob"),
        QuarantineParseStep(
            id=StepId("parsed"),
            source=ArgRef(ref=StepId("source")),
            instruction="parse",
            schema_ref="out",
        ),
    )
    parses = []
    provider = FakeProvider(
        {
            "Plan": lambda prompt: child if "CHILD" in prompt else outer,
            "Output": lambda _: parses.append(True) or Output(),
        }
    )
    run = RunSession(
        ctx=context(),
        registry=ToolRegistry(),
        grant=GRANT,
        declass=DenyAll(),
        planner=PLLM(provider, grant=GRANT),
        quarantine=QLLM(provider),
        q_schemas={"out": Output},
        sink=MemoryTraceSink(),
        limits=RunLimits(max_q_parses=1),
    )
    assert run.run().status == "aborted" and parses == [True]


def test_quarantine_timeout_never_emits_late_events_or_calls_next_tool():
    release, finished = threading.Event(), threading.Event()

    def hung(_):
        release.wait(timeout=5)
        finished.set()
        return Output()

    plan = plan_for(
        ConstStep(id=StepId("source"), value="blob"),
        QuarantineParseStep(
            id=StepId("parsed"),
            source=ArgRef(ref=StepId("source")),
            instruction="parse",
            schema_ref="out",
        ),
        write_step(),
    )
    provider = FakeProvider({"Plan": plan, "Output": hung})
    sink = MemoryTraceSink()
    run = RunSession(
        ctx=context(),
        registry=registry_for(lambda _: pytest.fail("must not call")),
        grant=GRANT,
        declass=DenyAll(),
        planner=PLLM(provider, grant=GRANT),
        quarantine=QLLM(provider),
        q_schemas={"out": Output},
        sink=sink,
        limits=RunLimits(reasoner_timeout_s=0.1),
    )
    try:
        assert run.run().status == "aborted"
        before = sink.read(RunId("test"))
    finally:
        release.set()
    assert finished.wait(timeout=2)
    assert sink.read(RunId("test")) == before


def test_sqlite_unavailable_is_a_sanitized_storage_error(tmp_path):
    with pytest.raises(TraceStorageError, match="cannot open audit database"):
        SQLiteTraceSink(tmp_path / "secret-missing-dir" / "db")
    sink = SQLiteTraceSink(tmp_path / "db")
    sink.close()
    with pytest.raises(TraceStorageError, match="cannot read audit events"):
        sink.read(RunId("r"))


def test_invalid_prebuilt_plan_is_revalidated_before_any_effect():
    calls = []
    plan = plan_for(write_step())
    plan.final = StepId("missing")
    result = session(registry_for(lambda _: calls.append(True) or Output()), plan=plan).run()
    assert result.status == "errored" and not calls


def test_type_changing_normalization_is_not_mistaken_for_unchanged_data():
    class Changed(BaseModel):
        public: list[object]

        @model_validator(mode="before")
        @classmethod
        def normalize(cls, data):
            if data.get("hidden"):
                data["public"] = [True]  # Python equality alone considers [True] == [1]
            return data

    spec = registry_for(lambda _: Output(), schema=Changed).catalog()[0]
    checked = Gate(GRANT, DenyAll()).authorize(
        spec, {"public": trusted([1]), "hidden": tainted("secret")}, context()
    )
    assert checked.args["public"].label.is_tainted
    assert not checked.verdict.allowed
