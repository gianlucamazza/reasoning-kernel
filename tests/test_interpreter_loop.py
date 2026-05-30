"""The Conductor walks the plan in order, wires the value store, and commits at the end."""

from __future__ import annotations

from reasoning_kernel.demo.email_exfil import CLEAN_BODY, benign_plan, make_world, run_scenario
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.trace import (
    PlanEmitted,
    QParseResult,
    RunCommitted,
    StepStarted,
)


def test_run_emits_plan_first_and_commit_last() -> None:
    trace = run_scenario(
        run_id="r",
        query="summarize and send to me",
        world=make_world(CLEAN_BODY),
        plan=benign_plan(RunId("r")),
        summary_text="ok",
    )
    assert isinstance(trace.events[0], PlanEmitted)
    assert isinstance(trace.events[-1], RunCommitted)


def test_each_step_is_started_and_quarantine_recorded() -> None:
    trace = run_scenario(
        run_id="r",
        query="summarize and send to me",
        world=make_world(CLEAN_BODY),
        plan=benign_plan(RunId("r")),
        summary_text="ok",
    )
    started = [e for e in trace.events if isinstance(e, StepStarted)]
    assert len(started) == 4  # const, read_inbox, q_parse, send
    assert any(isinstance(e, QParseResult) for e in trace.events)


def test_seq_is_monotonic() -> None:
    trace = run_scenario(
        run_id="r",
        query="x",
        world=make_world(CLEAN_BODY),
        plan=benign_plan(RunId("r")),
        summary_text="ok",
    )
    seqs = [e.seq for e in trace.events]
    assert seqs == list(range(len(seqs)))
