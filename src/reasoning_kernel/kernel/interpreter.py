"""The Conductor — the execution loop. Governs flow; does not reason.

It assembles the planner context (Invariant A), obtains a typed ``Plan``, and walks the steps.
``ToolCallStep`` is the only step kind that can reach reality, and it reaches it *only* through
the ``EffectDispatcher`` (which always checks the Gate first). The Conductor never holds a tool
callable and never calls a model except via the two reasoner roles. It is responsible for
termination (``RunLimits``) and fails closed on any plan it cannot safely execute.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ValidationError

from reasoning_kernel.context.assembler import build_planner_context, build_quarantine_context
from reasoning_kernel.kernel.effects import EffectBlocked, EffectDispatcher, ToolExecutionError
from reasoning_kernel.kernel.runtime import (
    DEFAULT_EXECUTOR,
    ReasonerExecutor,
    RunBoundExceeded,
    RunBudget,
)
from reasoning_kernel.kernel.taint import join_labels, quarantine_label
from reasoning_kernel.memory.sink import TraceStorageError
from reasoning_kernel.memory.store import ValueStore
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import ReasonerError
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.reasoner.telemetry import measure
from reasoning_kernel.schemas.capability import Capability, CapabilitySet
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.plan import (
    ConstStep,
    MergeStep,
    PlanStep,
    QuarantineParseStep,
    SubKernelStep,
    ToolCallStep,
)
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import (
    PlanEmitted,
    PlanRejected,
    QParseResult,
    ReasonerCall,
    RunAborted,
    RunBlocked,
    RunCommitted,
    RunErrored,
    RunResult,
    StepStarted,
    digest,
)
from reasoning_kernel.schemas.values import TaintedValue

# Errors that mean "the model produced a plan the kernel cannot safely execute", or a reasoner
# failed to return usable output. They stop subsequent steps, preserving prior effect evidence.
_PLAN_ERRORS = (ValidationError, ValueError, KeyError, ReasonerError)


_RunAborted = RunBoundExceeded


class Interpreter:
    def __init__(
        self,
        *,
        planner: PLLM,
        quarantine: QLLM,
        dispatcher: EffectDispatcher,
        trace: TraceWriter,
        q_schemas: dict[str, type[BaseModel]],
        limits: RunLimits = RunLimits(),
        depth: int = 0,
        budget: RunBudget | None = None,
        executor: ReasonerExecutor | None = None,
    ) -> None:
        # A reasoner may never plan beyond the kernel's authority (the §5.4 composition invariant).
        if not planner.grant.is_subset_of(dispatcher.grant()):
            raise ValueError("planner grant exceeds the dispatcher's capability grant")
        self._planner = planner
        self._quarantine = quarantine
        self._dispatcher = dispatcher
        self._trace = trace
        self._q_schemas = q_schemas.copy()
        self._limits = limits
        self._depth = depth
        self._store = ValueStore()  # replaced per run() with the query's label
        self._budget = budget if budget is not None else RunBudget(limits)
        self._executor = executor or DEFAULT_EXECUTOR
        self._run_lock = threading.Lock()
        self._used = False

    def run(self, ctx: RunContext) -> RunResult:
        with self._run_lock:
            if self._used:
                raise ValueError("interpreter is single-use")
            if not self._dispatcher.matches(ctx, self._trace):
                raise ValueError("run context or trace differs from dispatcher")
            self._used = True
        try:
            return self._run(ctx)
        except TraceStorageError:
            return self._closed("audit_failed")
        except Exception:
            # Unexpected host/schema/policy errors still stop before any further effect.
            try:
                self._trace.emit(RunErrored(run_id=ctx.run_id, reason="host_error"))
            except TraceStorageError:
                return self._closed("audit_failed")
            return self._closed("errored")

    def _run(self, ctx: RunContext) -> RunResult:
        # Per-run state — the store is labelled with the run's (trusted) query.
        self._store = ValueStore(ctx.query.label)
        prompt = build_planner_context(ctx.query.text, self._dispatcher.catalog(), self._q_schemas)

        try:
            plan = self._call_reasoner(
                lambda: self._planner.plan(prompt, run_id=ctx.run_id), ctx, "planner"
            )
        except _PLAN_ERRORS as exc:
            self._trace.emit(PlanRejected(run_id=ctx.run_id, reason=str(exc)))
            return self._closed("errored")
        except _RunAborted as ab:
            self._trace.emit(RunAborted(run_id=ctx.run_id, reason=ab.reason))
            return self._closed("aborted")
        self._trace.emit(PlanEmitted(run_id=ctx.run_id, plan=plan))

        try:
            self._budget.consume("max_steps", len(plan.steps))
        except _RunAborted as ab:
            self._trace.emit(RunAborted(run_id=ctx.run_id, reason=ab.reason))
            return self._closed("aborted")

        for step in plan.steps:
            self._trace.emit(StepStarted(run_id=ctx.run_id, step=step, step_id=step.id))
            try:
                value = self._eval_step(step, ctx)
            except EffectBlocked:
                self._trace.emit(RunBlocked(run_id=ctx.run_id, tool=_tool_name(step)))
                return self._closed("blocked")
            except _RunAborted as ab:
                self._trace.emit(RunAborted(run_id=ctx.run_id, step_id=step.id, reason=ab.reason))
                return self._closed("aborted")
            except ToolExecutionError as exc:
                self._trace.emit(RunErrored(run_id=ctx.run_id, step_id=step.id, reason=exc.code))
                return self._closed("errored")
            except _PLAN_ERRORS as exc:
                self._trace.emit(RunErrored(run_id=ctx.run_id, step_id=step.id, reason=str(exc)))
                return self._closed("errored")
            self._store.put(step.id, value)

        final = self._store.get(plan.final)
        self._trace.emit(
            RunCommitted(
                run_id=ctx.run_id,
                final_digest="" if self._trace.operational else digest(final.value),
            )
        )
        return RunResult(
            trace=self._trace.snapshot(),
            committed=final,
            status="succeeded",
            effects=self._trace.outcomes(),
        )

    def _closed(
        self, status: Literal["blocked", "aborted", "errored", "audit_failed"] = "errored"
    ) -> RunResult:
        """No final value; completed/uncertain effects remain explicit."""
        return RunResult(
            trace=self._trace.snapshot(),
            committed=None,
            status=status,
            effects=self._trace.outcomes(),
        )

    def _eval_step(self, step: PlanStep, ctx: RunContext) -> TaintedValue:
        if isinstance(step, ConstStep):
            # A planner literal inherits the (trusted) query's label — not hardcoded trust.
            return TaintedValue(value=step.value, label=ctx.query.label, produced_by=step.id)
        if isinstance(step, QuarantineParseStep):
            self._budget.consume("max_q_parses")
            src = self._store.resolve(step.source)
            if step.schema_ref not in self._q_schemas:
                raise ValueError(
                    f"unknown q_parse schema_ref {step.schema_ref!r} "
                    f"(available: {', '.join(self._q_schemas)})"
                )
            schema = self._q_schemas[step.schema_ref]
            q_prompt = build_quarantine_context(str(src.value), step.instruction)
            parsed = self._call_reasoner(
                lambda: self._quarantine.parse_blob(prompt=q_prompt, schema=schema),
                ctx,
                "quarantine",
            )
            label = quarantine_label(src.label)
            self._trace.emit(QParseResult(run_id=ctx.run_id, step_id=step.id, label=label))
            return TaintedValue(value=parsed, label=label, produced_by=step.id)
        if isinstance(step, ToolCallStep):
            self._budget.consume("max_effects")
            named = {k: self._store.resolve(a) for k, a in step.args.items()}
            return self._dispatcher.dispatch(step.tool, named, step_id=step.id)
        if isinstance(step, MergeStep):
            return self._eval_merge(step, ctx)
        # Only SubKernelStep remains. This is exhaustive over PlanStep: the param type makes pyright
        # error here if a new step kind is added to the union but not handled above.
        return self._eval_subkernel(step, ctx)

    def _eval_merge(self, step: MergeStep, ctx: RunContext) -> TaintedValue:
        # Combine the named inputs into one dict, labelled with the join of their labels: taint only
        # ever increases (sources union + DERIVED, readers intersected, subjects union). The
        # object-level over-approximation is sound — strictly safer than per-field labels.
        resolved = {k: self._store.resolve(ref) for k, ref in step.inputs.items()}
        merged: dict[str, object] = {k: tv.value for k, tv in resolved.items()}
        label = join_labels([tv.label for tv in resolved.values()])
        return TaintedValue(value=merged, label=label, produced_by=step.id)

    def _eval_subkernel(self, step: SubKernelStep, ctx: RunContext) -> TaintedValue:
        if self._limits.max_depth is not None and self._depth + 1 > self._limits.max_depth:
            raise _RunAborted(f"sub-kernel depth exceeds max_depth {self._limits.max_depth}")
        src = self._store.resolve(step.source)

        # Clamp the requested grant to the outer authority — a sub-kernel can never widen it.
        requested = frozenset(Capability(name=n) for n in step.grant)
        inner_grant = CapabilitySet(granted=requested & self._dispatcher.grant().granted)

        # The sub-planner's query is the (trusted) instruction plus the UNTRUSTED blob, labelled by
        # the blob's label, so every literal it produces inherits that taint (Invariant A).
        sub_text = f"{step.instruction}\n\n--- untrusted content ---\n{src.value}"
        sub_ctx = RunContext(
            run_id=RunId(uuid.uuid4().hex),
            user=ctx.user,
            query=TrustedQuery(text=sub_text, label=src.label),
        )
        self._trace.register_child(sub_ctx.run_id, ctx.run_id)
        sub = Interpreter(
            planner=self._planner.for_grant(inner_grant),
            quarantine=self._quarantine,
            dispatcher=self._dispatcher.for_subkernel(inner_grant, sub_ctx),
            trace=self._trace,  # shared: sub events interleave under the suffixed run_id
            q_schemas=self._q_schemas,
            limits=self._limits,
            depth=self._depth + 1,
            budget=self._budget,
            executor=self._executor,
        )
        result = sub.run(sub_ctx)
        if result.committed is None:
            if result.status == "audit_failed":
                raise TraceStorageError("child audit failed")
            if result.status == "aborted":
                raise _RunAborted("sub-kernel budget or timeout exceeded")
            # The child has no final value; earlier child effects remain in the shared audit.
            raise ValueError(f"sub-kernel {step.id} did not commit")
        # The outer value must dominate everything the sub touched: join source + sub-final labels.
        label = join_labels([quarantine_label(src.label), result.committed.label])
        return TaintedValue(value=result.committed.value, label=label, produced_by=step.id)

    def _call_reasoner[T](self, thunk: Callable[[], T], ctx: RunContext, role: str) -> T:
        """Bound the wait and admission; timed-out calls keep a slot until actual completion."""
        self._budget.consume("max_llm_calls")
        started = time.monotonic()
        value, metrics = self._executor.call(
            lambda: measure(thunk), self._limits.reasoner_timeout_s
        )
        for metric in metrics:
            self._trace.emit(
                ReasonerCall(
                    run_id=ctx.run_id,
                    role=role,
                    provider=metric.provider,
                    model=metric.model,
                    elapsed_s=time.monotonic() - started,
                    input_tokens=metric.usage.input_tokens,
                    output_tokens=metric.usage.output_tokens,
                    cache_read_tokens=metric.usage.cache_read_tokens,
                    reasoning_tokens=metric.usage.reasoning_tokens,
                )
            )
        return value


def _tool_name(step: PlanStep) -> str:
    return step.tool if isinstance(step, ToolCallStep) else "<none>"
