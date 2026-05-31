"""The data-subject dimension closes L2 at the mechanism: third-party data is not auto-released."""

from __future__ import annotations

from conftest import ctx, trusted

from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.taint import join_labels, quarantine_label, result_label
from reasoning_kernel.schemas.capability import Capability, CapabilitySet, EffectLevel
from reasoning_kernel.schemas.policy import VerifierVerdict
from reasoning_kernel.schemas.provenance import DataSubject, ProvenanceLabel, Source
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.values import TaintedValue
from reasoning_kernel.tools.demo_mail import SendEmailIn, SendEmailOut

CAP_SEND = Capability(name="mail.send")
CAP_READ = Capability(name="contacts.read")


def test_read_result_carries_declared_subjects() -> None:
    spec = ToolSpec(
        name="read_contacts",
        input_schema=SendEmailOut,
        output_schema=SendEmailOut,
        required_caps=frozenset({CAP_READ}),
        effect_level=EffectLevel.READ,
        result_subjects=frozenset({DataSubject.THIRD_PARTY}),
    )
    assert result_label(spec, []).has_third_party


def test_quarantine_preserves_subjects() -> None:
    src = ProvenanceLabel(
        sources=frozenset({Source.TOOL_READ}),
        readers=frozenset(),
        subjects=frozenset({DataSubject.THIRD_PARTY}),
    )
    assert quarantine_label(src).has_third_party  # the Q-LLM cannot launder the subject


def test_join_unions_subjects() -> None:
    a = ProvenanceLabel(
        sources=frozenset({Source.USER_QUERY}), subjects=frozenset({DataSubject.USER})
    )
    b = ProvenanceLabel(
        sources=frozenset({Source.TOOL_READ}), subjects=frozenset({DataSubject.THIRD_PARTY})
    )
    assert join_labels([a, b]).subjects == frozenset({DataSubject.USER, DataSubject.THIRD_PARTY})


class _RecordingDeclass:
    def __init__(self) -> None:
        self.called = False

    def may_declassify(self, *args: object, **kwargs: object) -> VerifierVerdict:
        self.called = True
        return VerifierVerdict(allowed=False, reason="recorded")


def test_third_party_routes_to_declass_even_when_readers_allow() -> None:
    # An arg whose readers WOULD permit the cap, but which is third-party, must still be sent to
    # declassification (the readers fast-path must not auto-release third-party data).
    spec = ToolSpec(
        name="send_email",
        input_schema=SendEmailIn,
        output_schema=SendEmailOut,
        required_caps=frozenset({CAP_SEND}),
        effect_level=EffectLevel.WRITE,
    )
    body = TaintedValue(
        value="Alice; Bob",
        label=ProvenanceLabel(
            sources=frozenset({Source.TOOL_READ}),
            readers=frozenset({CAP_SEND}),  # readers WOULD allow mail.send
            subjects=frozenset({DataSubject.THIRD_PARTY}),
        ),
        produced_by="t",  # type: ignore[arg-type]
    )
    recorder = _RecordingDeclass()
    gate = Gate(CapabilitySet(granted=frozenset({CAP_SEND})), recorder)
    verdict = gate.check(spec, {"to": trusted("user@example.com"), "body": body}, ctx())
    assert recorder.called  # forced to declass despite permissive readers
    assert not verdict.allowed
