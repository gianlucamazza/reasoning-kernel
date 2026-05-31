"""The Conductor — the execution loop. Governs flow; does not reason.

It assembles the planner context (Invariant A), obtains a typed ``Plan``, and walks the steps.
``ToolCallStep`` is the only step kind that can reach reality, and it reaches it *only* through
the ``EffectDispatcher`` (which always checks the Gate first). The Conductor never holds a tool
callable and never calls a model except via the two reasoner roles. It is responsible for
termination (``RunLimits``) and fails closed on any plan it cannot safely execute.
"""

from __future__ import annotations

import concurrent.futures as futures
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from reasoning_kernel.context.assembler import build_planner_context, build_quarantine_context
from reasoning_kernel.kernel.effects import EffectBlocked, EffectDispatcher
from reasoning_kernel.kernel.taint import join_labels, quarantine_label
from reasoning_kernel.memory.store import ValueStore
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import ReasonerError
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import Capability, CapabilitySet
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.plan import (
    ConstStep,
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
# failed to return usable output. They are failed closed (recorded, no effect committed), not
# crashes. Unexpected errors still propagate.
_PLAN_ERRORS = (ValidationError, ValueError, KeyError, ReasonerError)


class _RunAborted(Exception):
    """A run bound (RunLimits) was exceeded. Fails closed, like EffectBlocked."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
    ) -> None:
        # A reasoner may never plan beyond the kernel's authority (the §5.4 composition invariant).
        if not planner.grant.is_subset_of(dispatcher.grant()):
            raise ValueError("planner grant exceeds the dispatcher's capability grant")
        self._planner = planner
        self._quarantine = quarantine
        self._dispatcher = dispatcher
        self._trace = trace
        self._q_schemas = q_schemas
        self._limits = limits
        self._depth = depth
        self._store = ValueStore()  # replaced per run() with the query's label
        self._effects = 0
        self._q_parses = 0

    def run(self, ctx: RunContext) -> RunResult:
        # Per-run state — the store is labelled with the run's (trusted) query.
        self._store = ValueStore(ctx.query.label)
        self._effects = 0
        self._q_parses = 0
        prompt = build_planner_context(ctx.query.text, self._dispatcher.catalog(), self._q_schemas)

        try:
            plan = self._call_reasoner(lambda: self._planner.plan(prompt, run_id=ctx.run_id))
        except _PLAN_ERRORS as exc:
            self._trace.emit(PlanRejected(run_id=ctx.run_id, reason=str(exc)))
            return self._closed()
        except _RunAborted as ab:
            self._trace.emit(RunAborted(run_id=ctx.run_id, reason=ab.reason))
            return self._closed()
        self._trace.emit(PlanEmitted(run_id=ctx.run_id, plan=plan))

        if self._limits.max_steps is not None and len(plan.steps) > self._limits.max_steps:
            self._trace.emit(
                RunAborted(
                    run_id=ctx.run_id,
                    reason=f"plan has {len(plan.steps)} steps > max_steps {self._limits.max_steps}",
                )
            )
            return self._closed()

        for step in plan.steps:
            self._trace.emit(StepStarted(run_id=ctx.run_id, step=step))
            try:
                value = self._eval_step(step, ctx)
            except EffectBlocked:
                self._trace.emit(RunBlocked(run_id=ctx.run_id, tool=_tool_name(step)))
                return self._closed()
            except _RunAborted as ab:
                self._trace.emit(RunAborted(run_id=ctx.run_id, step_id=step.id, reason=ab.reason))
                return self._closed()
            except _PLAN_ERRORS as exc:
                self._trace.emit(RunErrored(run_id=ctx.run_id, step_id=step.id, reason=str(exc)))
                return self._closed()
            self._store.put(step.id, value)

        final = self._store.get(plan.final)
        self._trace.emit(RunCommitted(run_id=ctx.run_id, final_digest=digest(final.value)))
        return RunResult(trace=self._trace.snapshot(), committed=final)

    def _closed(self) -> RunResult:
        """A fail-closed outcome: the trace so far, with nothing committed."""
        return RunResult(trace=self._trace.snapshot(), committed=None)

    def _eval_step(self, step: PlanStep, ctx: RunContext) -> TaintedValue:
        if isinstance(step, ConstStep):
            # A planner literal inherits the (trusted) query's label — not hardcoded trust.
            return TaintedValue(value=step.value, label=ctx.query.label, produced_by=step.id)
        if isinstance(step, QuarantineParseStep):
            self._q_parses += 1
            if self._limits.max_q_parses is not None and self._q_parses > self._limits.max_q_parses:
                raise _RunAborted(f"q_parse count exceeds max_q_parses {self._limits.max_q_parses}")
            src = self._store.resolve(step.source)
            if step.schema_ref not in self._q_schemas:
                raise ValueError(
                    f"unknown q_parse schema_ref {step.schema_ref!r} "
                    f"(available: {', '.join(self._q_schemas)})"
                )
            schema = self._q_schemas[step.schema_ref]
            q_prompt = build_quarantine_context(str(src.value), step.instruction)
            parsed = self._call_reasoner(
                lambda: self._quarantine.parse_blob(prompt=q_prompt, schema=schema)
            )
            label = quarantine_label(src.label)
            self._trace.emit(QParseResult(run_id=ctx.run_id, step_id=step.id, label=label))
            return TaintedValue(value=parsed, label=label, produced_by=step.id)
        if isinstance(step, ToolCallStep):
            self._effects += 1
            if self._limits.max_effects is not None and self._effects > self._limits.max_effects:
                raise _RunAborted(f"effect count exceeds max_effects {self._limits.max_effects}")
            named = {k: self._store.resolve(a) for k, a in step.args.items()}
            return self._dispatcher.dispatch(step.tool, named)
        # Only SubKernelStep remains. This is exhaustive over PlanStep: the param type makes pyright
        # error here if a new step kind is added to the union but not handled above.
        return self._eval_subkernel(step, ctx)

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
            run_id=RunId(f"{ctx.run_id}/{step.id}"),
            user=ctx.user,
            query=TrustedQuery(text=sub_text, label=src.label),
        )
        sub = Interpreter(
            planner=self._planner.for_grant(inner_grant),
            quarantine=self._quarantine,
            dispatcher=self._dispatcher.for_subkernel(inner_grant, sub_ctx),
            trace=self._trace,  # shared: sub events interleave under the suffixed run_id
            q_schemas=self._q_schemas,
            limits=self._limits,
            depth=self._depth + 1,
        )
        result = sub.run(sub_ctx)
        if result.committed is None:
            # The sub-kernel committed nothing (blocked/aborted/errored): the task failed closed.
            raise ValueError(f"sub-kernel {step.id} did not commit")
        # The outer value must dominate everything the sub touched: join source + sub-final labels.
        label = join_labels([quarantine_label(src.label), result.committed.label])
        return TaintedValue(value=result.committed.value, label=label, produced_by=step.id)

    def _call_reasoner[T](self, thunk: Callable[[], T]) -> T:
        """Invoke a reasoner, enforcing the optional per-call timeout (deterministic when unset).

        On timeout the run aborts *immediately*: we must not use the executor as a context manager,
        because its ``__exit__`` calls ``shutdown(wait=True)`` and would block on the very call we
        timed out. We shut down without waiting; Python cannot kill the orphan thread, so the bound
        is on the run, not on the underlying call (which still relies on the provider's timeout).
        """
        timeout = self._limits.reasoner_timeout_s
        if timeout is None:
            return thunk()
        pool = futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(thunk)
        try:
            return future.result(timeout=timeout)
        except futures.TimeoutError:
            raise _RunAborted(f"reasoner call exceeded {timeout}s") from None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


def _tool_name(step: PlanStep) -> str:
    return step.tool if isinstance(step, ToolCallStep) else "<none>"
