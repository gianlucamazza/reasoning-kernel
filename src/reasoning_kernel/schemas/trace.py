"""The auditable record (Memory/Trace role): an append-only log of everything that happened.

Every plan, step, gate decision, commit, and block becomes a ``TraceEvent``. The trace is the
home the paper gives to auditability: a wrong or blocked decision leaves a record of what was
decided and why. Events carry a monotonic ``seq`` (assigned by the writer) rather than a wall
clock, so traces are deterministic and comparable in tests.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import Plan, PlanStep
from reasoning_kernel.schemas.policy import VerifierVerdict
from reasoning_kernel.schemas.provenance import ProvenanceLabel
from reasoning_kernel.schemas.values import TaintedValue


def digest(value: object) -> str:
    """A short, stable content digest for trace records (not a security primitive)."""
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:12]


class TraceEvent(BaseModel):
    """Base event. ``kind`` discriminates; ``seq`` is assigned by the TraceWriter on emit."""

    kind: str = "event"
    run_id: RunId
    seq: int = -1


class PlanEmitted(TraceEvent):
    kind: str = "plan_emitted"
    plan: Plan


class StepStarted(TraceEvent):
    kind: str = "step_started"
    step: PlanStep


class QParseResult(TraceEvent):
    kind: str = "q_parse_result"
    step_id: StepId
    label: ProvenanceLabel


class GateDecision(TraceEvent):
    kind: str = "gate_decision"
    tool: str
    verdict: VerifierVerdict
    arg_labels: list[ProvenanceLabel]


class EffectCommitted(TraceEvent):
    kind: str = "effect_committed"
    tool: str
    output_digest: str


class EffectBlockedEvent(TraceEvent):
    kind: str = "effect_blocked"
    tool: str
    verdict: VerifierVerdict


class RunCommitted(TraceEvent):
    kind: str = "run_committed"
    final_digest: str


class RunBlocked(TraceEvent):
    kind: str = "run_blocked"
    tool: str


class PlanRejected(TraceEvent):
    kind: str = "plan_rejected"
    reason: str


class RunErrored(TraceEvent):
    kind: str = "run_errored"
    step_id: StepId | None = None
    reason: str


class RunAborted(TraceEvent):
    kind: str = "run_aborted"
    step_id: StepId | None = None
    reason: str


class RunTrace(BaseModel):
    """An immutable snapshot of a run's event log."""

    run_id: RunId
    events: list[TraceEvent]


class RunResult(BaseModel):
    """A run's outcome: the audit trace plus the committed final value (None if not committed)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace: RunTrace
    committed: TaintedValue | None = None
