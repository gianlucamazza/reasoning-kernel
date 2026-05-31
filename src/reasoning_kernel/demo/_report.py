"""Shared, human-readable rendering of a trace event for the demos.

Keeps one line per event and, crucially, surfaces the *reason* a decision was made — the gate's
verdict, or why a run aborted / was rejected — which the raw `kind`/`tool` alone does not show.
"""

from __future__ import annotations

from reasoning_kernel.schemas.trace import (
    EffectBlockedEvent,
    GateDecision,
    PlanEmitted,
    PlanRejected,
    RunAborted,
    RunErrored,
    TraceEvent,
)


def event_line(e: TraceEvent) -> str:
    """One readable line for a trace event, including the verdict/abort reason when present."""
    line = f"  [{e.seq:>2}] {e.kind}"
    tool = getattr(e, "tool", None)
    if tool is not None:
        line += f" tool={tool}"
    if isinstance(e, GateDecision | EffectBlockedEvent):
        line += f" allowed={e.verdict.allowed} reason={e.verdict.reason!r}"
    elif isinstance(e, RunAborted | RunErrored | PlanRejected):
        line += f" reason={e.reason!r}"
    elif isinstance(e, PlanEmitted):
        line += f" steps={[f'{s.kind}:{s.id}' for s in e.plan.steps]}"
    return line
