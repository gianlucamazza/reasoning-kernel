"""The Conductor — the execution loop. Governs flow; does not reason.

It assembles the planner context (Invariant A), obtains a typed ``Plan``, and walks the steps.
``ToolCallStep`` is the only step kind that can reach reality, and it reaches it *only* through
the ``EffectDispatcher`` (which always checks the Gate first). The Conductor never holds a tool
callable and never calls a model except via the two reasoner roles.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from reasoning_kernel.context.assembler import build_planner_context, build_quarantine_context
from reasoning_kernel.kernel.effects import EffectBlocked, EffectDispatcher
from reasoning_kernel.kernel.taint import quarantine_label
from reasoning_kernel.memory.store import ValueStore
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.plan import ConstStep, QuarantineParseStep, ToolCallStep
from reasoning_kernel.schemas.policy import RunContext
from reasoning_kernel.schemas.provenance import ProvenanceLabel
from reasoning_kernel.schemas.trace import (
    PlanEmitted,
    PlanRejected,
    QParseResult,
    RunBlocked,
    RunCommitted,
    RunErrored,
    RunTrace,
    StepStarted,
    digest,
)
from reasoning_kernel.schemas.values import TaintedValue

# Errors that mean "the model produced a plan the kernel cannot safely execute". They are
# failed closed (recorded, no effect committed), not crashes. Unexpected errors still propagate.
_PLAN_ERRORS = (ValidationError, ValueError, KeyError)


class Interpreter:
    def __init__(
        self,
        *,
        planner: PLLM,
        quarantine: QLLM,
        dispatcher: EffectDispatcher,
        store: ValueStore,
        trace: TraceWriter,
        q_schemas: dict[str, type[BaseModel]],
    ) -> None:
        self._planner = planner
        self._quarantine = quarantine
        self._dispatcher = dispatcher
        self._store = store
        self._trace = trace
        self._q_schemas = q_schemas

    def run(self, ctx: RunContext) -> RunTrace:
        prompt = build_planner_context(ctx.query, self._dispatcher.catalog(), self._q_schemas)

        # Planning can fail closed: an invalid plan from the model commits nothing and is recorded.
        try:
            plan = self._planner.plan(prompt, run_id=ctx.run_id)
        except _PLAN_ERRORS as exc:
            self._trace.emit(PlanRejected(run_id=ctx.run_id, reason=str(exc)))
            return self._trace.snapshot()
        self._trace.emit(PlanEmitted(run_id=ctx.run_id, plan=plan))

        for step in plan.steps:
            self._trace.emit(StepStarted(run_id=ctx.run_id, step=step))
            try:
                value = self._eval_step(step, ctx)
            except EffectBlocked:
                # The gate denied a commit; the run aborts with the block recorded in the trace.
                self._trace.emit(RunBlocked(run_id=ctx.run_id, tool=_tool_name(step)))
                return self._trace.snapshot()
            except _PLAN_ERRORS as exc:
                # A bad reference, unknown schema, or invalid path: fail closed, commit nothing.
                self._trace.emit(RunErrored(run_id=ctx.run_id, step_id=step.id, reason=str(exc)))
                return self._trace.snapshot()
            self._store.put(step.id, value)

        self._trace.emit(
            RunCommitted(run_id=ctx.run_id, final_digest=digest(self._store.get(plan.final).value))
        )
        return self._trace.snapshot()

    def _eval_step(self, step: object, ctx: RunContext) -> TaintedValue:
        if isinstance(step, ConstStep):
            return TaintedValue(
                value=step.value, label=ProvenanceLabel.trusted(), produced_by=step.id
            )
        if isinstance(step, QuarantineParseStep):
            src = self._store.resolve(step.source)
            if step.schema_ref not in self._q_schemas:
                raise ValueError(
                    f"unknown q_parse schema_ref {step.schema_ref!r} "
                    f"(available: {', '.join(self._q_schemas)})"
                )
            schema = self._q_schemas[step.schema_ref]
            q_prompt = build_quarantine_context(str(src.value), step.instruction)
            parsed = self._quarantine.parse_blob(prompt=q_prompt, schema=schema)
            label = quarantine_label(src.label)
            self._trace.emit(QParseResult(run_id=ctx.run_id, step_id=step.id, label=label))
            return TaintedValue(value=parsed, label=label, produced_by=step.id)
        if isinstance(step, ToolCallStep):
            named = {k: self._store.resolve(a) for k, a in step.args.items()}
            return self._dispatcher.dispatch(step.tool, named)
        raise TypeError(f"unknown step kind: {type(step).__name__}")


def _tool_name(step: object) -> str:
    return step.tool if isinstance(step, ToolCallStep) else "<none>"
