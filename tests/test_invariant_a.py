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
from reasoning_kernel.memory.store import ValueStore
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import LLMResult
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.policy import RunContext
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    RecipientIsUserPolicy,
    build_registry,
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
    ctx = RunContext(run_id=RunId("r"), user=USER_EMAIL, query="summarize and send to me")
    trace_writer = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace_writer, ctx
    )
    Interpreter(
        planner=PLLM(spy),
        quarantine=QLLM(spy),
        dispatcher=dispatcher,
        store=ValueStore(),
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
