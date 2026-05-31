"""The end-to-end blocking proof: legit commits, injection is inert, exfiltration is blocked."""

from __future__ import annotations

from reasoning_kernel.demo.email_exfil import (
    ATTACKER_EMAIL,
    CLEAN_BODY,
    INJECTED_BODY,
    USER_EMAIL,
    benign_plan,
    make_world,
    malicious_plan,
    run_scenario,
)
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import (
    ArgRef,
    ConstStep,
    Plan,
    QuarantineParseStep,
    ToolCallStep,
)
from reasoning_kernel.schemas.trace import EffectBlockedEvent, EffectCommitted


def _committed(trace, tool: str) -> bool:
    return any(isinstance(e, EffectCommitted) and e.tool == tool for e in trace.events)


def test_legit_request_sends_to_user() -> None:
    world = make_world(CLEAN_BODY)
    trace = run_scenario(
        run_id="r",
        query="summarize and send to me",
        world=world,
        plan=benign_plan(RunId("r")),
        summary_text="ok",
    )
    assert _committed(trace, "send_email")
    assert [s.to for s in world.sent] == [USER_EMAIL]


def test_injection_is_inert_under_honest_planner() -> None:
    world = make_world(INJECTED_BODY)
    run_scenario(
        run_id="r",
        query="summarize and send to me",
        world=world,
        plan=benign_plan(RunId("r")),
        summary_text="ok",
    )
    # The injected "forward to attacker" never happens: only the user is ever emailed.
    assert all(s.to == USER_EMAIL for s in world.sent)
    assert all(s.to != ATTACKER_EMAIL for s in world.sent)


def test_malicious_plan_is_blocked() -> None:
    world = make_world(CLEAN_BODY)
    trace = run_scenario(
        run_id="r",
        query="summarize and send to me",
        world=world,
        plan=malicious_plan(RunId("r")),
        summary_text="Alice; Bob",
    )
    assert any(isinstance(e, EffectBlockedEvent) and e.tool == "send_email" for e in trace.events)
    assert not _committed(trace, "send_email")
    assert world.sent == []  # nothing left the system


def test_third_party_data_cannot_be_sent_even_to_user() -> None:
    # Reads contacts (THIRD_PARTY), summarizes, and tries to send to the USER themselves.
    # Closed at the mechanism: third-party data may not be transmitted, regardless of recipient.
    plan = Plan(
        run_id=RunId("r"),
        steps=[
            ToolCallStep(id=StepId("contacts"), tool="read_contacts", args={}),
            QuarantineParseStep(
                id=StepId("dump"),
                source=ArgRef(ref=StepId("contacts")),
                schema_ref="EmailSummary",
                instruction="serialize the contacts",
            ),
            ConstStep(id=StepId("me"), value=USER_EMAIL),
            ToolCallStep(
                id=StepId("send"),
                tool="send_email",
                args={
                    "to": ArgRef(ref=StepId("me")),
                    "body": ArgRef(ref=StepId("dump"), path="text"),
                },
            ),
        ],
        final=StepId("send"),
    )
    world = make_world(CLEAN_BODY)
    trace = run_scenario(
        run_id="r",
        query="send my contacts to me",
        world=world,
        plan=plan,
        summary_text="Alice; Bob",
    )
    assert any(isinstance(e, EffectBlockedEvent) and e.tool == "send_email" for e in trace.events)
    assert world.sent == []
