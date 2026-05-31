"""RecipientIsUserPolicy: every rejection branch of the demo declassifier is exercised directly."""

from __future__ import annotations

from conftest import ctx, tainted, trusted

from reasoning_kernel.schemas.capability import Capability, EffectLevel
from reasoning_kernel.schemas.provenance import DataSubject
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.tools.demo_mail import (
    CreateEventIn,
    CreateEventOut,
    RecipientIsUserPolicy,
    SendEmailIn,
    SendEmailOut,
)

POLICY = RecipientIsUserPolicy()
THIRD_PARTY = frozenset({DataSubject.THIRD_PARTY})


def _send_spec() -> ToolSpec:
    return ToolSpec(
        name="send_email",
        input_schema=SendEmailIn,
        output_schema=SendEmailOut,
        required_caps=frozenset({Capability(name="mail.send")}),
        effect_level=EffectLevel.WRITE,
    )


def _event_spec() -> ToolSpec:
    return ToolSpec(
        name="create_event",
        input_schema=CreateEventIn,
        output_schema=CreateEventOut,
        required_caps=frozenset({Capability(name="calendar.write")}),
        effect_level=EffectLevel.WRITE,
    )


def test_send_to_trusted_user_is_allowed() -> None:
    args = {"to": trusted("user@example.com"), "body": trusted("hi")}
    assert POLICY.may_declassify(_send_spec(), args, ctx()).allowed


def test_send_third_party_body_is_blocked() -> None:
    args = {"to": trusted("user@example.com"), "body": tainted("leak", subjects=THIRD_PARTY)}
    verdict = POLICY.may_declassify(_send_spec(), args, ctx())
    assert not verdict.allowed
    assert "third-party" in verdict.reason


def test_send_missing_recipient_is_blocked() -> None:
    verdict = POLICY.may_declassify(_send_spec(), {"body": trusted("hi")}, ctx())
    assert not verdict.allowed
    assert "missing recipient" in verdict.reason


def test_send_tainted_recipient_is_blocked() -> None:
    args = {"to": tainted("user@example.com"), "body": trusted("hi")}
    assert not POLICY.may_declassify(_send_spec(), args, ctx()).allowed


def test_send_to_other_recipient_is_blocked() -> None:
    args = {"to": trusted("attacker@evil.com"), "body": trusted("hi")}
    assert not POLICY.may_declassify(_send_spec(), args, ctx()).allowed


def test_tool_without_rule_is_blocked() -> None:
    spec = ToolSpec(
        name="other_tool",
        input_schema=SendEmailIn,
        output_schema=SendEmailOut,
        required_caps=frozenset({Capability(name="x")}),
        effect_level=EffectLevel.WRITE,
    )
    verdict = POLICY.may_declassify(spec, {}, ctx())
    assert not verdict.allowed
    assert "no declassification rule" in verdict.reason


def test_create_event_third_party_is_blocked() -> None:
    args = {"slot": tainted("2026-01-01", subjects=THIRD_PARTY)}
    assert not POLICY.may_declassify(_event_spec(), args, ctx()).allowed


def test_create_event_from_user_data_is_allowed() -> None:
    args = {"slot": trusted("2026-01-01")}
    assert POLICY.may_declassify(_event_spec(), args, ctx()).allowed
