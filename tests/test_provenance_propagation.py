"""Taint propagation: union of sources, intersection of readers, no laundering."""

from __future__ import annotations

from reasoning_kernel.kernel.taint import join_labels, quarantine_label, result_label
from reasoning_kernel.schemas.capability import Capability, EffectLevel
from reasoning_kernel.schemas.provenance import ProvenanceLabel, Source
from reasoning_kernel.schemas.registry import ToolSpec

CAP_X = Capability(name="x")
CAP_Y = Capability(name="y")


def test_join_unions_sources_and_marks_derived() -> None:
    a = ProvenanceLabel(sources=frozenset({Source.USER_QUERY}), readers=None)
    b = ProvenanceLabel(sources=frozenset({Source.TOOL_READ}), readers=frozenset({CAP_X}))
    joined = join_labels([a, b])
    assert Source.TOOL_READ in joined.sources
    assert Source.DERIVED in joined.sources  # >1 input
    assert joined.is_tainted


def test_join_intersects_readers_with_none_identity() -> None:
    a = ProvenanceLabel(sources=frozenset({Source.USER_QUERY}), readers=None)  # unrestricted
    b = ProvenanceLabel(sources=frozenset({Source.TOOL_READ}), readers=frozenset({CAP_X, CAP_Y}))
    c = ProvenanceLabel(sources=frozenset({Source.Q_LLM}), readers=frozenset({CAP_X}))
    joined = join_labels([a, b, c])
    assert joined.readers == frozenset({CAP_X})  # most restrictive wins; None is identity


def test_read_tool_result_is_tainted_and_scoped() -> None:
    spec = ToolSpec(
        name="read",
        input_schema=ProvenanceLabel,  # any BaseModel works as a placeholder schema here
        output_schema=ProvenanceLabel,
        required_caps=frozenset(),
        effect_level=EffectLevel.READ,
        result_readers=frozenset(),  # may flow into nothing
    )
    label = result_label(spec, [])
    assert Source.TOOL_READ in label.sources
    assert label.readers == frozenset()
    assert not label.allows_reader(CAP_X)


def test_quarantine_cannot_widen_readers() -> None:
    src = ProvenanceLabel(sources=frozenset({Source.TOOL_READ}), readers=frozenset())
    out = quarantine_label(src)
    assert Source.Q_LLM in out.sources
    assert out.readers == frozenset()  # still blocked; the Q-LLM cannot launder taint
