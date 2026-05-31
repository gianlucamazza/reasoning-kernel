"""Shared test helpers. The whole default suite is key-free and deterministic."""

from __future__ import annotations

from reasoning_kernel.schemas.capability import Capability
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery, VerifierVerdict
from reasoning_kernel.schemas.provenance import DataSubject, ProvenanceLabel, Source
from reasoning_kernel.schemas.values import TaintedValue


def tainted(
    value: object,
    *,
    readers: frozenset[Capability] = frozenset(),
    subjects: frozenset[DataSubject] = frozenset(),
) -> TaintedValue:
    return TaintedValue(
        value=value,
        label=ProvenanceLabel(
            sources=frozenset({Source.TOOL_READ}), readers=readers, subjects=subjects
        ),
        produced_by="t",  # type: ignore[arg-type]
    )


def trusted(value: object) -> TaintedValue:
    return TaintedValue(value=value, label=ProvenanceLabel.trusted(), produced_by="t")  # type: ignore[arg-type]


def ctx() -> RunContext:
    return RunContext(
        run_id="run-test",  # type: ignore[arg-type]
        user="user@example.com",
        query=TrustedQuery(text="do a thing"),
    )


class AllowAll:
    def may_declassify(self, *args: object, **kwargs: object) -> VerifierVerdict:
        return VerifierVerdict(allowed=True, reason="allow-all (test)")


class DenyAll:
    def may_declassify(self, *args: object, **kwargs: object) -> VerifierVerdict:
        return VerifierVerdict(allowed=False, reason="deny-all (test)")
