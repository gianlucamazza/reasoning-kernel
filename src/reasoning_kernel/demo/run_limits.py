"""Worked demo: RunLimits aborts a run closed when a bound is exceeded (the termination role).

The benign plan reads the inbox (effect 1) and sends a summary (effect 2). With ``max_effects=1``
the Conductor aborts *before* the second effect: ``read_inbox`` is committed, but NOTHING is sent —
the run fails closed, exactly like a gate block. A real oversized plan from a flaky model is bounded
the same way.

Run: ``uv run python -m reasoning_kernel.demo.run_limits``
"""

from __future__ import annotations

from reasoning_kernel.demo._report import event_line
from reasoning_kernel.demo.email_exfil import CLEAN_BODY, benign_plan, make_world, run_scenario
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.trace import EffectCommitted, RunAborted


def main() -> None:
    world = make_world(CLEAN_BODY)
    trace = run_scenario(
        run_id="run-limited",
        query="Summarize my latest email and send the summary to me.",
        world=world,
        plan=benign_plan(RunId("run-limited")),
        summary_text="Your boss confirms the 3pm meeting tomorrow.",
        limits=RunLimits(max_effects=1),
    )

    print("\n=== RunLimits: max_effects=1 aborts before the send ===")
    for e in trace.events:
        print(event_line(e))
    committed = [e.tool for e in trace.events if isinstance(e, EffectCommitted)]
    aborted = [e for e in trace.events if isinstance(e, RunAborted)]
    print(f"  -> committed effects: {committed or 'none'}")
    print(f"  -> emails actually sent to: {[s.to for s in world.sent] or 'nobody'}")

    if world.sent:
        raise RuntimeError("max_effects was not enforced — an email was sent")
    if not aborted:
        raise RuntimeError("run did not abort on the effect bound")

    print("\nResult: read_inbox committed; send_email blocked by max_effects; run ABORTED closed.")


if __name__ == "__main__":
    main()
