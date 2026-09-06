"""Deterministic capability, schema and provenance authorization before every tool call."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from reasoning_kernel.kernel.taint import join_labels
from reasoning_kernel.schemas.capability import CapabilitySet, EffectLevel
from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.policy import DeclassPolicy, RunContext, VerifierVerdict
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.trace import canonical_json
from reasoning_kernel.schemas.values import TaintedValue


@dataclass(frozen=True)
class CheckedCall:
    """Authorization plus the exact normalized input model that was checked."""

    model: BaseModel | None
    args: dict[str, TaintedValue]
    verdict: VerifierVerdict


class Gate:
    def __init__(self, grant: CapabilitySet, declass: DeclassPolicy) -> None:
        self._grant = grant
        self._declass = declass

    @property
    def grant(self) -> CapabilitySet:
        return self._grant

    def for_grant(self, grant: CapabilitySet) -> Gate:
        """Reduce authority even when called directly by an embedding."""
        return Gate(CapabilitySet(granted=grant.granted & self._grant.granted), self._declass)

    def _prepare(
        self,
        spec: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> tuple[BaseModel, dict[str, TaintedValue]]:
        # Validators must not mutate stored payloads or alter the comparison source.
        model = spec.input_schema(**{k: deepcopy(v.value) for k, v in named_args.items()})
        combined = join_labels([ctx.query.label, *(v.label for v in named_args.values())])
        normalized: dict[str, TaintedValue] = {}
        values: dict[str, object] = {key: getattr(model, key) for key in type(model).model_fields}
        values.update(model.model_extra or {})
        for key, value in values.items():
            original = named_args.get(key)
            try:
                unchanged = original is not None and canonical_json(value) == canonical_json(
                    original.value
                )
            except (ValueError, TypeError):
                unchanged = False  # opaque/custom objects conservatively inherit all input labels
            normalized[key] = TaintedValue(
                value=value,
                label=original.label if original is not None and unchanged else combined,
                produced_by=original.produced_by if original is not None else StepId("__default__"),
            )
        return model, normalized

    def check(
        self,
        spec: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> VerifierVerdict:
        """Compatibility API for callers needing only a verdict."""
        return self.authorize(spec, named_args, ctx).verdict

    def authorize(
        self,
        spec: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> CheckedCall:
        """All three checks, with no caller-supplied validation bypass."""
        missing = sorted(c.name for c in spec.required_caps if not self._grant.allows(c))
        if missing:
            return CheckedCall(
                None,
                named_args,
                VerifierVerdict(
                    allowed=False,
                    reason=f"missing capabilities for {spec.name}",
                    issues=[f"not granted: {m}" for m in missing],
                ),
            )
        try:
            model, normalized = self._prepare(spec, named_args, ctx)
        except ValidationError as exc:
            return CheckedCall(
                None,
                named_args,
                VerifierVerdict(
                    allowed=False,
                    reason=f"arguments do not satisfy {spec.input_schema.__name__}",
                    issues=[f"schema validation failed ({exc.error_count()} errors)"],
                ),
            )
        verdict = self._provenance(spec, normalized, ctx)
        return CheckedCall(model, normalized, verdict)

    def _provenance(
        self,
        spec: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> VerifierVerdict:
        if spec.effect_level >= EffectLevel.WRITE or spec.args_leave_boundary:
            tainted = [v for v in named_args.values() if v.label.is_tainted]
            has_third_party = any(v.label.has_third_party for v in named_args.values())
            if tainted or has_third_party:
                # Auto-release requires explicit readers on EVERY tainted argument, declared
                # capabilities and no third-party data. Unrestricted tainted readers are not safe.
                permitted = (
                    not has_third_party
                    and bool(spec.required_caps)
                    and all(
                        v.label.readers is not None and spec.required_caps <= v.label.readers
                        for v in tainted
                    )
                )
                if not permitted:
                    verdict = self._declass.may_declassify(spec, named_args, ctx)
                    if not verdict.allowed:
                        return VerifierVerdict(
                            allowed=False,
                            reason=f"untrusted-derived data may not flow into {spec.name}",
                            issues=verdict.issues or [verdict.reason],
                        )
                    return verdict
        return VerifierVerdict(allowed=True, reason=f"{spec.name} permitted")
