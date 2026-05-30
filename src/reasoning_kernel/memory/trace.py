"""The trace writer — an append-only sink for the auditable record.

Exposes only ``emit`` (append, assigning a monotonic ``seq``) and ``snapshot`` (read). There is
no mutate or delete: the record can grow and be read, never rewritten.
"""

from __future__ import annotations

from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.trace import RunTrace, TraceEvent


class TraceWriter:
    def __init__(self, run_id: RunId) -> None:
        self.run_id = run_id
        self._events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        event.seq = len(self._events)
        self._events.append(event)

    def snapshot(self) -> RunTrace:
        return RunTrace(run_id=self.run_id, events=list(self._events))
