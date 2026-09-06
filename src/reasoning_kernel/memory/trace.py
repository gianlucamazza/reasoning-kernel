"""The trace writer — an append-only sink for the auditable record.

Exposes only ``emit`` (append, assigning a monotonic ``seq``) and ``snapshot`` (read). There is
no mutate or delete: the record can grow and be read, never rewritten.
"""

from __future__ import annotations

import threading

from pydantic import JsonValue

from reasoning_kernel.memory.sink import TraceSink, TraceStorageError
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.trace import (
    AuditEvent,
    EffectCommitted,
    EffectFailed,
    EffectOutcome,
    EffectStarted,
    GateDecision,
    PlanRejected,
    QParseResult,
    ReasonerCall,
    RunAborted,
    RunBlocked,
    RunErrored,
    RunTrace,
    TraceEvent,
)


def audit_event(event: TraceEvent) -> AuditEvent:
    """Allowlist metadata; exclude plans, values, digests and raw exception text."""
    metadata: dict[str, JsonValue] = {}
    if isinstance(event, GateDecision):
        metadata = {
            "tool": event.tool,
            "allowed": event.verdict.allowed,
            "labels": [label.model_dump(mode="json") for label in event.arg_labels],
        }
    elif isinstance(event, EffectStarted | EffectCommitted | EffectFailed):
        metadata = {"tool": event.tool}
        if isinstance(event, EffectCommitted):
            metadata["output_valid"] = event.output_valid
        if isinstance(event, EffectFailed):
            metadata["code"] = event.code
    elif isinstance(event, QParseResult):
        metadata = {"label": event.label.model_dump(mode="json")}
    elif isinstance(event, ReasonerCall):
        metadata = {
            "role": event.role,
            "provider": event.provider,
            "model": event.model,
            "elapsed_s": event.elapsed_s,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "cache_read_tokens": event.cache_read_tokens,
            "reasoning_tokens": event.reasoning_tokens,
        }
    elif isinstance(event, PlanRejected):
        metadata = {"code": "plan_rejected"}
    elif isinstance(event, RunAborted):
        metadata = {"code": "run_bound_exceeded"}
    elif isinstance(event, RunBlocked):
        metadata = {"code": "gate_denied"}
    elif isinstance(event, RunErrored):
        metadata = {
            "code": event.reason
            if event.reason in {"tool_exception", "invalid_output", "host_error"}
            else "invalid_plan_step"
        }
    return AuditEvent(
        kind=event.kind,
        run_id=event.run_id,
        seq=event.seq,
        step_id=event.step_id,
        invocation_id=event.invocation_id,
        parent_run_id=event.parent_run_id,
        metadata=metadata,
    )


class TraceWriter:
    def __init__(
        self, run_id: RunId, *, sink: TraceSink | None = None, operational: bool = False
    ) -> None:
        self.run_id = run_id
        self.operational = operational
        self._sink = sink
        self._events: list[TraceEvent] = []
        self._effects: dict[str, EffectOutcome] = {}
        self._parents: dict[RunId, RunId] = {}
        self._step_ids: dict[tuple[RunId, StepId], StepId] = {}
        self._lock = threading.RLock()
        self._failed = False
        if sink is not None:
            sink.start(run_id)

    def register_child(self, child: RunId, parent: RunId) -> None:
        with self._lock:
            if child in self._parents or child == self.run_id:
                raise ValueError("duplicate child run")
            self._parents[child] = parent

    def owns(self, run_id: RunId) -> bool:
        return run_id == self.run_id or run_id in self._parents

    def emit(self, event: TraceEvent) -> None:
        with self._lock:
            if self._failed:
                raise TraceStorageError("audit writer unavailable")
            copied = event.model_copy(deep=True)
            copied.seq = len(self._events)
            copied.parent_run_id = self._parents.get(copied.run_id)
            safe = audit_event(copied)
            # Sub-planners see untrusted content: their chosen ids must not become an audit payload.
            if copied.step_id is not None:
                key = (copied.run_id, copied.step_id)
                if key not in self._step_ids:
                    self._step_ids[key] = StepId(f"step-{len(self._step_ids)}")
                safe.step_id = self._step_ids[key]
            if self._sink is not None:
                try:
                    self._sink.append(self.run_id, safe)
                except Exception:
                    self._failed = True
                    raise TraceStorageError("audit append failed") from None
            self._events.append(safe if self.operational else copied)
            if copied.invocation_id and isinstance(copied, EffectStarted | EffectCommitted):
                self._effects[copied.invocation_id] = EffectOutcome(
                    invocation_id=copied.invocation_id,
                    run_id=copied.run_id,
                    step_id=safe.step_id if self.operational else copied.step_id,
                    tool=copied.tool,
                    status="completed" if isinstance(copied, EffectCommitted) else "uncertain",
                    output_valid=copied.output_valid
                    if isinstance(copied, EffectCommitted)
                    else None,
                )

    def outcomes(self) -> list[EffectOutcome]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._effects.values()]

    def snapshot(self) -> RunTrace:
        with self._lock:
            return RunTrace(
                run_id=self.run_id, events=[e.model_copy(deep=True) for e in self._events]
            )
