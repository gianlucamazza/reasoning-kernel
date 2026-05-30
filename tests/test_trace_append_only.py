"""The trace writer is append-only: emit + snapshot, monotonic seq, no rewrite."""

from __future__ import annotations

from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.trace import RunBlocked


def test_emit_assigns_monotonic_seq() -> None:
    w = TraceWriter(RunId("r"))
    w.emit(RunBlocked(run_id=RunId("r"), tool="a"))
    w.emit(RunBlocked(run_id=RunId("r"), tool="b"))
    snap = w.snapshot()
    assert [e.seq for e in snap.events] == [0, 1]


def test_snapshot_is_a_copy() -> None:
    w = TraceWriter(RunId("r"))
    w.emit(RunBlocked(run_id=RunId("r"), tool="a"))
    snap = w.snapshot()
    w.emit(RunBlocked(run_id=RunId("r"), tool="b"))
    assert len(snap.events) == 1  # earlier snapshot unaffected by later emits


def test_writer_exposes_no_mutation_api() -> None:
    forbidden = {"delete", "remove", "pop", "clear", "update", "set"}
    assert forbidden.isdisjoint(set(dir(TraceWriter)))
