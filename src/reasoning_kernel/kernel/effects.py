"""The effect dispatcher — the one and only place a real tool callable is invoked.

This is where the no-bypass guarantee becomes structural rather than conventional:
- it is the sole holder of the registry's callables;
- it CANNOT be constructed without a ``Gate`` (the gate is a required constructor argument);
- ``dispatch`` calls ``gate.check`` unconditionally and raises ``EffectBlocked`` *before* the
  callable is ever reached.

So "no effect bypasses the Verifier" reduces to "the only effect site always checks first" —
which is true by construction, and witnessed in every trace.
"""

from __future__ import annotations

from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.taint import result_label
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.schemas.capability import CapabilitySet
from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.policy import RunContext, VerifierVerdict
from reasoning_kernel.schemas.trace import EffectBlockedEvent, EffectCommitted, GateDecision, digest
from reasoning_kernel.schemas.values import TaintedValue
from reasoning_kernel.tools.registry import ToolRegistry


class EffectBlocked(Exception):
    """Raised when the Verifier denies a call. Carries the verdict; the callable did not run."""

    def __init__(self, verdict: VerifierVerdict) -> None:
        super().__init__(verdict.reason)
        self.verdict = verdict


class EffectDispatcher:
    def __init__(
        self,
        registry: ToolRegistry,
        gate: Gate,
        trace: TraceWriter,
        ctx: RunContext,
    ) -> None:
        self._registry = registry
        self._gate = gate
        self._trace = trace
        self._ctx = ctx

    def catalog(self):
        return self._registry.catalog()

    def grant(self) -> CapabilitySet:
        """The capability grant the Gate enforces (the run's authority ceiling)."""
        return self._gate.grant

    def for_subkernel(self, grant: CapabilitySet, ctx: RunContext) -> EffectDispatcher:
        """A dispatcher over the SAME registry and shared trace, at a reduced grant (a sub-kernel).

        Same registry means the inner kernel cannot reach a callable the outer one couldn't; the
        clamped Gate means it can authorize strictly less. Every effect still routes through a Gate.
        """
        return EffectDispatcher(self._registry, self._gate.for_grant(grant), self._trace, ctx)

    def dispatch(self, tool_name: str, named_args: dict[str, TaintedValue]) -> TaintedValue:
        rtool = self._registry.get(tool_name)
        spec = rtool.spec
        arg_labels = [v.label for v in named_args.values()]

        verdict = self._gate.check(spec, named_args, self._ctx)
        self._trace.emit(
            GateDecision(
                run_id=self._ctx.run_id, tool=spec.name, verdict=verdict, arg_labels=arg_labels
            )
        )
        if not verdict.allowed:
            self._trace.emit(
                EffectBlockedEvent(run_id=self._ctx.run_id, tool=spec.name, verdict=verdict)
            )
            raise EffectBlocked(verdict)

        # Past the gate: build the validated input model and invoke the real callable.
        model_in = spec.input_schema(**{k: v.value for k, v in named_args.items()})
        out = rtool.callable(model_in)
        self._trace.emit(
            EffectCommitted(run_id=self._ctx.run_id, tool=spec.name, output_digest=digest(out))
        )
        return TaintedValue(
            value=out,
            label=result_label(spec, arg_labels),
            produced_by=StepId(f"__effect__{spec.name}"),
        )
