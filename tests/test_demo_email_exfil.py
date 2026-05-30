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
from reasoning_kernel.schemas.ids import RunId
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
