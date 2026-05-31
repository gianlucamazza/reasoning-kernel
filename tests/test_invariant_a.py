"""Invariant A: the privileged planner never sees untrusted content.

Two checks: (1) the assembled planner context is built from the query + tool catalog only, so it
cannot contain the injected email body; (2) end-to-end, a spy provider records the exact prompt
each reasoner receives — the P-LLM's prompt excludes the untrusted body, while the Q-LLM's prompt
contains it (correct: the quarantined parser is the only one that sees untrusted content, with no
tools to act on it).
"""

from __future__ import annotations

from reasoning_kernel.context.assembler import build_planner_context
from reasoning_kernel.demo.email_exfil import INJECTED_BODY, USER_EMAIL, benign_plan, make_world
from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import LLMResult
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.provenance import ProvenanceLabel, Source
from reasoning_kernel.schemas.trace import EffectBlockedEvent, RunCommitted
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    RecipientIsUserPolicy,
    build_registry,
)


def _run_benign(query: TrustedQuery, world):
    spy = FakeProvider({"Plan": benign_plan(RunId("r")), "EmailSummary": EmailSummary(text="ok")})
    ctx = RunContext(run_id=RunId("r"), user=USER_EMAIL, query=query)
    trace = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace, ctx
    )
    return (
        Interpreter(
            planner=PLLM(spy, grant=DEMO_GRANT),
            quarantine=QLLM(spy),
            dispatcher=dispatcher,
            trace=trace,
            q_schemas=Q_SCHEMAS,
        )
        .run(ctx)
        .trace
    )


# Markers that appear in INJECTED_BODY but must never reach the planner.
_MARKERS = ["attacker@evil.com", "ignore previous instructions"]


def test_planner_context_excludes_untrusted_content() -> None:
    catalog = build_registry(make_world(INJECTED_BODY)).catalog()
    prompt = build_planner_context(
        "Summarize my latest email and send it to me.", catalog, Q_SCHEMAS
    )
    lowered = prompt.lower()
    for marker in _MARKERS:
        assert marker not in lowered


class _SpyProvider(FakeProvider):
    """Records the prompt passed for each requested schema."""

    def __init__(self, responses) -> None:
        super().__init__(responses)
        self.prompts: dict[str, str] = {}

    def parse(self, *, prompt, schema, system, model, max_tokens, cache_system=True) -> LLMResult:
        self.prompts[schema.__name__] = prompt
        return super().parse(
            prompt=prompt,
            schema=schema,
            system=system,
            model=model,
            max_tokens=max_tokens,
            cache_system=cache_system,
        )


def test_planner_never_receives_the_email_body_endtoend() -> None:
    world = make_world(INJECTED_BODY)
    spy = _SpyProvider({"Plan": benign_plan(RunId("r")), "EmailSummary": EmailSummary(text="ok")})
    ctx = RunContext(
        run_id=RunId("r"), user=USER_EMAIL, query=TrustedQuery(text="summarize and send to me")
    )
    trace_writer = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace_writer, ctx
    )
    Interpreter(
        planner=PLLM(spy, grant=DEMO_GRANT),
        quarantine=QLLM(spy),
        dispatcher=dispatcher,
        trace=trace_writer,
        q_schemas=Q_SCHEMAS,
    ).run(ctx)

    planner_prompt = spy.prompts["Plan"].lower()
    quarantine_prompt = spy.prompts["EmailSummary"].lower()
    # The planner (P-LLM) must not have seen the injected body...
    for marker in _MARKERS:
        assert marker not in planner_prompt
    # ...while the quarantined parser (Q-LLM) does — and it has no tools to act on it.
    assert "attacker@evil.com" in quarantine_prompt


def test_const_label_derives_from_query() -> None:
    # The benign plan's recipient is a const. With a trusted query it commits; with a query whose
    # label forbids flow into mail.send, the const inherits that label and the send is blocked —
    # proving const labels DERIVE from the query, not a hardcoded `trusted()`.
    from reasoning_kernel.demo.email_exfil import CLEAN_BODY

    trusted_q = TrustedQuery(text="summarize and send to me")
    committed = _run_benign(trusted_q, make_world(CLEAN_BODY))
    assert any(isinstance(e, RunCommitted) for e in committed.events)

    untrusted_q = TrustedQuery(
        text="summarize and send to me",
        label=ProvenanceLabel(sources=frozenset({Source.TOOL_READ}), readers=frozenset()),
    )
    blocked = _run_benign(untrusted_q, make_world(CLEAN_BODY))
    assert any(isinstance(e, EffectBlockedEvent) for e in blocked.events)
    assert not any(isinstance(e, RunCommitted) for e in blocked.events)
