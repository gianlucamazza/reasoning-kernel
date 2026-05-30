"""Stage 1 of the Verifier: a missing capability denies, regardless of provenance."""

from __future__ import annotations

from conftest import ctx, trusted

from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.schemas.capability import Capability, CapabilitySet, EffectLevel
from reasoning_kernel.schemas.policy import VerifierVerdict
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.tools.demo_mail import ReadInboxIn, ReadInboxOut, SendEmailIn, SendEmailOut

CAP_NEED = Capability(name="need.it")


class _Deny:
    def may_declassify(self, *a: object, **k: object) -> VerifierVerdict:
        return VerifierVerdict(allowed=False, reason="n/a")


def _spec(level: EffectLevel) -> ToolSpec:
    return ToolSpec(
        name="t",
        input_schema=ReadInboxIn,
        output_schema=ReadInboxOut,
        required_caps=frozenset({CAP_NEED}),
        effect_level=level,
    )


def test_missing_capability_denies() -> None:
    gate = Gate(CapabilitySet(granted=frozenset()), _Deny())
    verdict = gate.check(_spec(EffectLevel.READ), {}, ctx())
    assert not verdict.allowed
    assert any("need.it" in i for i in verdict.issues)


def test_granted_capability_allows_untainted_read() -> None:
    gate = Gate(CapabilitySet(granted=frozenset({CAP_NEED})), _Deny())
    verdict = gate.check(_spec(EffectLevel.READ), {}, ctx())
    assert verdict.allowed


def test_bad_arguments_fail_schema_stage() -> None:
    gate = Gate(CapabilitySet(granted=frozenset({CAP_NEED})), _Deny())
    spec = ToolSpec(
        name="t",
        input_schema=SendEmailIn,
        output_schema=SendEmailOut,
        required_caps=frozenset({CAP_NEED}),
        effect_level=EffectLevel.READ,  # READ so the schema stage decides, not provenance
    )
    # SendEmailIn requires both 'to' and 'body'; omitting 'body' violates the schema.
    verdict = gate.check(spec, {"to": trusted("x@y")}, ctx())
    assert not verdict.allowed
    assert "SendEmailIn" in verdict.reason
