"""Provenance labels — the taint a value carries through the interpreter.

This is the §6.1 mechanism: the kernel does not *sanitize* untrusted text, it *scopes the
capabilities* that untrusted-derived data is permitted to flow into. A label records where
a value came from (``sources``) and which capabilities it may flow into (``readers``).
``readers=None`` means unrestricted, reserved for purely trusted data.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from reasoning_kernel.schemas.capability import Capability


class Source(StrEnum):
    """Origin of a value. ``TOOL_READ`` and ``Q_LLM`` taint; ``DERIVED`` is an audit marker."""

    USER_QUERY = "user_query"  # the controlled query and planner literals (trusted)
    TOOL_READ = "tool_read"  # anything a READ tool returned (untrusted)
    Q_LLM = "q_llm"  # anything the quarantined reasoner produced (untrusted)
    DERIVED = "derived"  # combined from >1 input (audit marker; not itself taint)


class DataSubject(StrEnum):
    """Whose data a value is about — orthogonal to trust, used for declassification scoping."""

    USER = "user"  # the requesting user's own data
    THIRD_PARTY = "third_party"  # anyone else (contacts, other inboxes, ...)


# Taint derives only from the presence of an actually-untrusted origin. DERIVED records that a
# value combines >1 input but does not taint by itself: a merge of purely trusted inputs stays
# trusted (the union of real sources carries the taint whenever any input was untrusted).
_UNTRUSTED: frozenset[Source] = frozenset({Source.TOOL_READ, Source.Q_LLM})


class ProvenanceLabel(BaseModel):
    """Immutable provenance label: where a value came from, where it may flow, who it is about."""

    model_config = ConfigDict(frozen=True)

    sources: frozenset[Source]
    readers: frozenset[Capability] | None = None  # None = unrestricted (trusted only)
    subjects: frozenset[DataSubject] = frozenset()  # empty = no third-party content

    @property
    def is_tainted(self) -> bool:
        return bool(self.sources & _UNTRUSTED)

    @property
    def has_third_party(self) -> bool:
        return DataSubject.THIRD_PARTY in self.subjects

    def allows_reader(self, cap: Capability) -> bool:
        """True if a value with this label may flow into an effect requiring ``cap``."""
        if self.readers is None:
            return True
        return cap in self.readers

    @classmethod
    def trusted(cls) -> ProvenanceLabel:
        """A label for data derived solely from the controlled user query."""
        return cls(sources=frozenset({Source.USER_QUERY}), readers=None, subjects=frozenset())
