"""Stage 3 of the Verifier: tainted data may not flow into a WRITE unless declassified."""

from __future__ import annotations

import pytest
from conftest import AllowAll, DenyAll, ctx, tainted, trusted
from pydantic import ValidationError

from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.schemas.capability import CapabilitySet, EffectLevel
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.tools.demo_mail import (
    CAP_MAIL_SEND,
    RecipientIsUserPolicy,
    SendEmailIn,
    SendEmailOut,
)

SEND_SPEC = ToolSpec(
    name="send_email",
    input_schema=SendEmailIn,
    output_schema=SendEmailOut,
    required_caps=frozenset({CAP_MAIL_SEND}),
    effect_level=EffectLevel.WRITE,
)
GRANT = CapabilitySet(granted=frozenset({CAP_MAIL_SEND}))


def test_tainted_write_denied_without_declassification() -> None:
    gate = Gate(GRANT, DenyAll())
    args = {"to": trusted("attacker@evil.com"), "body": tainted("secret contacts")}
    verdict = gate.check(SEND_SPEC, args, ctx())
    assert not verdict.allowed


def test_tainted_write_allowed_when_declassified() -> None:
    gate = Gate(GRANT, AllowAll())
    args = {"to": trusted("user@example.com"), "body": tainted("secret")}
    verdict = gate.check(SEND_SPEC, args, ctx())
    assert verdict.allowed


def test_untainted_write_needs_no_declassification() -> None:
    gate = Gate(GRANT, DenyAll())  # would deny if consulted
    args = {"to": trusted("anyone@example.com"), "body": trusted("hello")}
    verdict = gate.check(SEND_SPEC, args, ctx())
    assert verdict.allowed  # declass never consulted: nothing is tainted


def test_recipient_is_user_policy_allows_self_blocks_others() -> None:
    gate = Gate(GRANT, RecipientIsUserPolicy())
    to_self = {"to": trusted("user@example.com"), "body": tainted("my own summary")}
    to_other = {"to": trusted("attacker@evil.com"), "body": tainted("my own summary")}
    assert gate.check(SEND_SPEC, to_self, ctx()).allowed
    assert not gate.check(SEND_SPEC, to_other, ctx()).allowed


def test_write_tool_must_declare_a_capability() -> None:
    # A WRITE with no required capability is rejected at construction (it would give the provenance
    # check nothing to reason about). Prevents the footgun at the source.
    with pytest.raises(ValidationError):
        ToolSpec(
            name="leak",
            input_schema=SendEmailIn,
            output_schema=SendEmailOut,
            required_caps=frozenset(),
            effect_level=EffectLevel.WRITE,
        )


def test_gate_denies_tainted_into_capless_write_defense_in_depth() -> None:
    # Bypass the construction guard with model_construct to prove the GATE itself does not treat an
    # empty capability set as a free pass for tainted data into a WRITE.
    capless_write = ToolSpec.model_construct(
        name="leak",
        input_schema=SendEmailIn,
        output_schema=SendEmailOut,
        required_caps=frozenset(),
        effect_level=EffectLevel.WRITE,
        result_readers=frozenset(),
    )
    gate = Gate(CapabilitySet(granted=frozenset()), DenyAll())
    args = {"to": trusted("attacker@evil.com"), "body": tainted("secret contacts")}
    assert not gate.check(capless_write, args, ctx()).allowed
