"""Provenance propagation — how taint flows and narrows through the interpreter.

Rules (paper section 6.1):
- join: ``sources = union(sources_i)`` (add ``DERIVED`` when combining >1 input);
  ``readers = intersection(readers_i)`` with ``None`` (unrestricted) as the identity element.
- a READ tool's output is freshly untrusted: add ``TOOL_READ`` and narrow ``readers`` to the
  tool's declared ``result_readers``.
- a Q-LLM parse cannot launder taint: it keeps the source blob's label and adds ``Q_LLM``.

Restrictiveness only ever increases as untrusted data flows.
"""

from __future__ import annotations

from collections.abc import Sequence

from reasoning_kernel.schemas.capability import Capability, EffectLevel
from reasoning_kernel.schemas.provenance import DataSubject, ProvenanceLabel, Source
from reasoning_kernel.schemas.registry import ToolSpec


def join_labels(labels: Sequence[ProvenanceLabel]) -> ProvenanceLabel:
    if not labels:
        return ProvenanceLabel.trusted()
    sources: set[Source] = set()
    subjects: set[DataSubject] = set()
    for label in labels:
        sources |= label.sources
        subjects |= label.subjects
    if len(labels) > 1:
        sources.add(Source.DERIVED)

    readers: frozenset[Capability] | None = None
    for label in labels:
        if label.readers is None:
            continue
        readers = label.readers if readers is None else (readers & label.readers)
    return ProvenanceLabel(
        sources=frozenset(sources), readers=readers, subjects=frozenset(subjects)
    )


def result_label(spec: ToolSpec, arg_labels: Sequence[ProvenanceLabel]) -> ProvenanceLabel:
    """Provenance of a tool's output, given its argument labels."""
    base = join_labels(arg_labels)
    sources = set(base.sources)
    readers = base.readers
    subjects = base.subjects | spec.result_subjects  # subjects only ever accumulate
    if spec.effect_level == EffectLevel.READ:
        sources.add(Source.TOOL_READ)
        rr = spec.result_readers
        readers = rr if readers is None else (readers & rr)
    return ProvenanceLabel(
        sources=frozenset(sources), readers=readers, subjects=frozenset(subjects)
    )


def quarantine_label(source_label: ProvenanceLabel) -> ProvenanceLabel:
    """The label of a Q-LLM parse result: source taint and subjects preserved, ``Q_LLM`` added.

    The Q-LLM cannot launder ``subjects`` any more than it can launder ``sources``: a summary of
    third-party data is still third-party data.
    """
    return ProvenanceLabel(
        sources=frozenset(source_label.sources | {Source.Q_LLM}),
        readers=source_label.readers,
        subjects=source_label.subjects,
    )
