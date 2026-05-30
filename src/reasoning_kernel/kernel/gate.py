"""The Verifier — the single logical Invariant-B boundary.

Every consequential call is checked here, deterministically, in three stages:
  1. capability — the grant must contain every capability the tool requires;
  2. schema     — the arguments must validate against the tool's input schema;
  3. provenance — for a WRITE, no tainted argument may flow into a required capability unless
     the (deterministic) declassification policy explicitly allows it.

There is no LLM on this path: verification never depends on trusting a probabilistic component
(the paper's §6.2 distinction between a real, deterministic boundary and a probabilistic one).
"""

from __future__ import annotations

from pydantic import ValidationError

from reasoning_kernel.schemas.capability import CapabilitySet, EffectLevel
from reasoning_kernel.schemas.policy import DeclassPolicy, RunContext, VerifierVerdict
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.values import TaintedValue


class Gate:
    def __init__(self, grant: CapabilitySet, declass: DeclassPolicy) -> None:
        self._grant = grant
        self._declass = declass

    def check(
        self,
        spec: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> VerifierVerdict:
        # 1. capability
        missing = sorted(c.name for c in spec.required_caps if not self._grant.allows(c))
        if missing:
            return VerifierVerdict(
                allowed=False,
                reason=f"missing capabilities for {spec.name}",
                issues=[f"not granted: {m}" for m in missing],
            )

        # 2. schema
        try:
            spec.input_schema(**{k: v.value for k, v in named_args.items()})
        except ValidationError as exc:
            return VerifierVerdict(
                allowed=False,
                reason=f"arguments do not satisfy {spec.input_schema.__name__}",
                issues=[str(exc)],
            )

        # 3. provenance (only matters for WRITE effects)
        if spec.effect_level >= EffectLevel.WRITE:
            tainted_into_cap = any(
                v.label.is_tainted and not v.label.allows_reader(cap)
                for cap in spec.required_caps
                for v in named_args.values()
            )
            if tainted_into_cap:
                verdict = self._declass.may_declassify(spec, named_args, ctx)
                if not verdict.allowed:
                    return VerifierVerdict(
                        allowed=False,
                        reason=f"untrusted-derived data may not flow into {spec.name}",
                        issues=verdict.issues or [verdict.reason],
                    )
                return verdict

        return VerifierVerdict(allowed=True, reason=f"{spec.name} permitted")
