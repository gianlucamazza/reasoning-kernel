"""The auditable record (Memory/Trace role): an append-only log of everything that happened.

Every plan, step, gate decision, commit, and block becomes a ``TraceEvent``. The trace is the
home the paper gives to auditability: a wrong or blocked decision leaves a record of what was
decided and why. Events carry a monotonic ``seq`` assigned by the writer; invocation IDs and
measured latency are operational metadata, not deterministic test fixtures.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import Enum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SerializeAsAny

from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import Plan, PlanStep
from reasoning_kernel.schemas.policy import VerifierVerdict
from reasoning_kernel.schemas.provenance import ProvenanceLabel
from reasoning_kernel.schemas.values import TaintedValue


def digest(value: object) -> str:
    """A short, stable content digest for trace records (not a security primitive)."""
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def _canonical(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return _canonical({k: getattr(value, k) for k in type(value).model_fields})
    if isinstance(value, Enum):
        return _canonical(value.value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if not all(isinstance(k, str) for k in mapping):
            raise ValueError("digest requires string mapping keys")
        return {str(k): _canonical(v) for k, v in mapping.items()}
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in cast("list[object] | tuple[object, ...]", value)]
    if isinstance(value, set | frozenset):
        items = cast("set[object] | frozenset[object]", value)
        return sorted((_canonical(v) for v in items), key=lambda v: json.dumps(v, sort_keys=True))
    raise ValueError("unsupported digest payload")


class TraceEvent(BaseModel):
    """Base event. ``kind`` discriminates; ``seq`` is assigned by the TraceWriter on emit."""

    kind: str = "event"
    run_id: RunId
    seq: int = -1
    schema_version: Literal[1] = 1
    step_id: StepId | None = None
    invocation_id: str | None = None
    parent_run_id: RunId | None = None


class AuditEvent(TraceEvent):
    """Payload-free operational event and persistent wire representation."""

    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EffectStarted(TraceEvent):
    kind: str = "effect_started"
    tool: str


class EffectFailed(TraceEvent):
    kind: str = "effect_failed"
    tool: str
    code: str


class ReasonerCall(TraceEvent):
    kind: str = "reasoner_call"
    role: str
    provider: str
    model: str
    elapsed_s: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0


class PlanEmitted(TraceEvent):
    kind: str = "plan_emitted"
    plan: Plan


class StepStarted(TraceEvent):
    kind: str = "step_started"
    step: PlanStep


class QParseResult(TraceEvent):
    kind: str = "q_parse_result"
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
    output_valid: bool = True


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
    """A detached snapshot: mutations never affect its writer or another snapshot."""

    run_id: RunId
    events: list[SerializeAsAny[TraceEvent]]


class EffectOutcome(BaseModel):
    invocation_id: str
    run_id: RunId
    step_id: StepId | None = None
    tool: str
    status: Literal["completed", "uncertain"]
    output_valid: bool | None = None


class RunResult(BaseModel):
    """A run's outcome: the audit trace plus the committed final value (None if not committed)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace: RunTrace
    committed: TaintedValue | None = None
    status: Literal["succeeded", "blocked", "aborted", "errored", "audit_failed"] = "errored"
    effects: list[EffectOutcome] = Field(default_factory=list[EffectOutcome])
