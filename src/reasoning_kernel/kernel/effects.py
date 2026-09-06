"""The effect dispatcher — the one and only place a real tool callable is invoked.

This is where the no-bypass guarantee becomes structural rather than conventional:
- it is the sole holder of the registry's callables;
- it CANNOT be constructed without a ``Gate`` (the gate is a required constructor argument);
- ``dispatch`` calls ``gate.authorize`` unconditionally and raises ``EffectBlocked`` *before* the
  callable is ever reached.

So "no effect bypasses the Verifier" reduces to "the only effect site always checks first" —
which is true by construction, and witnessed in every trace.
"""

from __future__ import annotations

import uuid

from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.taint import result_label
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.schemas.capability import CapabilitySet
from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.policy import RunContext, VerifierVerdict
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.trace import (
    EffectBlockedEvent,
    EffectCommitted,
    EffectFailed,
    EffectStarted,
    GateDecision,
    digest,
)
from reasoning_kernel.schemas.values import TaintedValue
from reasoning_kernel.tools.registry import ToolRegistry


class EffectBlocked(Exception):
    """Raised when the Verifier denies a call. Carries the verdict; the callable did not run."""

    def __init__(self, verdict: VerifierVerdict) -> None:
        super().__init__(verdict.reason)
        self.verdict = verdict


class ToolExecutionError(Exception):
    """A tool failed or returned invalid output; previous/external effects are not rolled back."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EffectDispatcher:
    def __init__(
        self,
        registry: ToolRegistry,
        gate: Gate,
        trace: TraceWriter,
        ctx: RunContext,
    ) -> None:
        self._registry = registry.snapshot()
        self._gate = gate
        self._trace = trace
        self._ctx = ctx

    def catalog(self) -> list[ToolSpec]:
        return [
            spec
            for spec in self._registry.catalog()
            if self._gate.grant.allows_all(spec.required_caps)
        ]

    def matches(self, ctx: RunContext, trace: TraceWriter) -> bool:
        return ctx == self._ctx and trace is self._trace and trace.owns(ctx.run_id)

    def grant(self) -> CapabilitySet:
        """The capability grant the Gate enforces (the run's authority ceiling)."""
        return self._gate.grant

    def for_subkernel(self, grant: CapabilitySet, ctx: RunContext) -> EffectDispatcher:
        """A dispatcher over the SAME registry and shared trace, at a reduced grant (a sub-kernel).

        Same registry means the inner kernel cannot reach a callable the outer one couldn't; the
        clamped Gate means it can authorize strictly less. Every effect still routes through a Gate.
        """
        return EffectDispatcher(self._registry, self._gate.for_grant(grant), self._trace, ctx)

    def dispatch(
        self, tool_name: str, named_args: dict[str, TaintedValue], *, step_id: StepId | None = None
    ) -> TaintedValue:
        rtool = self._registry.get(tool_name)
        spec = rtool.spec
        invocation_id = uuid.uuid4().hex
        checked = self._gate.authorize(spec, named_args, self._ctx)
        model_in, named_args, verdict = checked.model, checked.args, checked.verdict
        arg_labels = [v.label for v in named_args.values()]
        self._trace.emit(
            GateDecision(
                run_id=self._ctx.run_id,
                tool=spec.name,
                verdict=verdict,
                arg_labels=arg_labels,
                step_id=step_id,
                invocation_id=invocation_id,
            )
        )
        if not verdict.allowed:
            self._trace.emit(
                EffectBlockedEvent(
                    run_id=self._ctx.run_id,
                    tool=spec.name,
                    verdict=verdict,
                    step_id=step_id,
                    invocation_id=invocation_id,
                )
            )
            raise EffectBlocked(verdict)

        # Past the gate: invoke with the same normalized model that was authorized.
        assert model_in is not None
        self._trace.emit(
            EffectStarted(
                run_id=self._ctx.run_id,
                tool=spec.name,
                step_id=step_id,
                invocation_id=invocation_id,
            )
        )
        try:
            out = rtool.callable(model_in)
        except Exception:
            self._trace.emit(
                EffectFailed(
                    run_id=self._ctx.run_id,
                    tool=spec.name,
                    step_id=step_id,
                    invocation_id=invocation_id,
                    code="tool_exception",
                )
            )
            raise ToolExecutionError("tool_exception") from None
        try:
            # Revalidate even existing model instances; a callable may have mutated one.
            if not isinstance(out, spec.output_schema):
                raise TypeError("tool returned the wrong output model")
            validated = spec.output_schema.model_validate(out.model_dump(by_alias=True))
        except Exception:
            self._trace.emit(
                EffectCommitted(
                    run_id=self._ctx.run_id,
                    tool=spec.name,
                    step_id=step_id,
                    invocation_id=invocation_id,
                    output_digest="",
                    output_valid=False,
                )
            )
            raise ToolExecutionError("invalid_output") from None
        try:
            output_digest = "" if self._trace.operational else digest(validated)
        except (ValueError, TypeError):
            output_digest = ""  # custom payloads never prevent recording a completed call
        self._trace.emit(
            EffectCommitted(
                run_id=self._ctx.run_id,
                tool=spec.name,
                output_digest=output_digest,
                step_id=step_id,
                invocation_id=invocation_id,
            )
        )
        return TaintedValue(
            value=validated,
            label=result_label(spec, arg_labels),
            produced_by=step_id or StepId(f"__effect__{spec.name}"),
        )
