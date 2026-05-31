"""Capabilities and effect levels — the unit of authority the Verifier enforces.

A capability is an unforgeable name for a permission (e.g. ``mail.send``). The kernel
grants a fixed ``CapabilitySet`` per run; a tool declares the capabilities it requires.
Authority flows only through explicit grants — the object-capability discipline the paper
borrows (Hardy 1988, the confused-deputy problem).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from pydantic import BaseModel, ConfigDict


class EffectLevel(IntEnum):
    """Ordered severity of a tool's side effect. Higher = more dangerous."""

    PURE = 0  # no external read, no side effect
    READ = 1  # reads external/private data (introduces untrusted content)
    WRITE = 2  # mutates or transmits externally (the commit the Verifier most guards)


@dataclass(frozen=True)
class Capability:
    """A named permission. Frozen (hashable) so it can live in a ``frozenset``."""

    name: str

    def __str__(self) -> str:
        return self.name


class CapabilitySet(BaseModel):
    """The authority granted to a single run. Immutable."""

    model_config = ConfigDict(frozen=True)

    granted: frozenset[Capability]

    def allows(self, cap: Capability) -> bool:
        return cap in self.granted

    def allows_all(self, caps: frozenset[Capability]) -> bool:
        return caps <= self.granted

    def is_subset_of(self, other: CapabilitySet) -> bool:
        """True if contained in ``other`` — a child reasoner may not widen authority."""
        return self.granted <= other.granted
