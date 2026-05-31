"""Worked demo: a MergeStep combines several reads into one value; taint flows through the join.

"Summarize my latest email AND my contact list, then send it to me." A `MergeStep` materializes a
composite of the inbox (USER) and contacts (THIRD_PARTY) so the single-`source` Q-LLM parse can
summarize both at once. The merge's label is the JOIN of its inputs — third-party from contacts
included — so the follow-up send to the user is BLOCKED: folding third-party data into the value
taints the whole result (object-level over-approximation, the safe default).

Run: ``uv run python -m reasoning_kernel.demo.merge``
"""

from __future__ import annotations

from reasoning_kernel.demo._report import event_line
from reasoning_kernel.demo.email_exfil import CLEAN_BODY, USER_EMAIL, make_world, run_scenario
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import (
    ArgRef,
    ConstStep,
    MergeStep,
    Plan,
    QuarantineParseStep,
    ToolCallStep,
)
from reasoning_kernel.schemas.trace import EffectBlockedEvent, EffectCommitted


def _merge_plan(run_id: RunId) -> Plan:
    return Plan(
        run_id=run_id,
        steps=[
            ConstStep(id=StepId("me"), value=USER_EMAIL),
            ToolCallStep(id=StepId("inbox"), tool="read_inbox", args={}),
            ToolCallStep(id=StepId("contacts"), tool="read_contacts", args={}),
            MergeStep(
                id=StepId("brief"),
                inputs={
                    "email": ArgRef(ref=StepId("inbox"), path="latest.body"),
                    "contacts": ArgRef(ref=StepId("contacts")),
                },
            ),
            QuarantineParseStep(
                id=StepId("summary"),
                source=ArgRef(ref=StepId("brief")),
                schema_ref="EmailSummary",
                instruction="Summarize the email and the contact list.",
            ),
            ToolCallStep(
                id=StepId("send"),
                tool="send_email",
                args={
                    "to": ArgRef(ref=StepId("me")),
                    "body": ArgRef(ref=StepId("summary"), path="text"),
                },
            ),
        ],
        final=StepId("send"),
    )


def main() -> None:
    world = make_world(CLEAN_BODY)
    trace = run_scenario(
        run_id="run-merge",
        query="Summarize my latest email together with my contacts and send it to me.",
        world=world,
        plan=_merge_plan(RunId("run-merge")),
        summary_text="Meeting at 3pm; contacts: Alice.",
    )

    print("\n=== MergeStep: composite of inbox + contacts; taint flows through the join ===")
    for e in trace.events:
        print(event_line(e))
    committed = [e.tool for e in trace.events if isinstance(e, EffectCommitted)]
    blocked = [e.tool for e in trace.events if isinstance(e, EffectBlockedEvent)]
    print(f"  -> committed effects: {committed or 'none'}; blocked: {blocked or 'none'}")
    print(f"  -> emails actually sent to: {[s.to for s in world.sent] or 'nobody'}")

    if world.sent:
        raise RuntimeError("the merged third-party data was sent — taint did not propagate")

    print("\nResult: merge folded in contacts; the join carried THIRD_PARTY; the send was BLOCKED.")


if __name__ == "__main__":
    main()
