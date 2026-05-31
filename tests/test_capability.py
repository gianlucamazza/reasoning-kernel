"""Capability algebra: the set operations the Verifier and sub-kernel grant-clamping rely on."""

from __future__ import annotations

from reasoning_kernel.schemas.capability import Capability, CapabilitySet

A = Capability(name="a")
B = Capability(name="b")
C = Capability(name="c")


def test_allows_single() -> None:
    cs = CapabilitySet(granted=frozenset({A, B}))
    assert cs.allows(A)
    assert not cs.allows(C)


def test_allows_all_is_subset_semantics() -> None:
    cs = CapabilitySet(granted=frozenset({A, B}))
    assert cs.allows_all(frozenset({A}))
    assert cs.allows_all(frozenset({A, B}))
    assert cs.allows_all(frozenset())  # the empty requirement is always satisfied
    assert not cs.allows_all(frozenset({A, C}))


def test_is_subset_of_cannot_widen() -> None:
    child = CapabilitySet(granted=frozenset({A}))
    parent = CapabilitySet(granted=frozenset({A, B}))
    assert child.is_subset_of(parent)
    assert not parent.is_subset_of(child)  # a child may not widen the parent's authority
