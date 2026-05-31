"""Worked demo: a failing reasoner makes the run fail CLOSED (commits nothing).

When the planner's provider returns no usable structured output it raises ``ReasonerError``; the
Conductor records a ``plan_rejected`` and commits nothing. Treating the model as untrusted compute
means a flaky reasoner can never produce a partial effect.

Run: ``uv run python -m reasoning_kernel.demo.reasoner_error``
"""

from __future__ import annotations

from pydantic import BaseModel

from reasoning_kernel.demo._report import event_line
from reasoning_kernel.demo.email_exfil import CLEAN_BODY, USER_EMAIL, make_world
from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import LLMResult, ReasonerError
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery
from reasoning_kernel.schemas.trace import EffectCommitted, PlanRejected
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    RecipientIsUserPolicy,
    build_registry,
)


class FailingProvider:
    """A provider that always fails to return a usable result (empty / refused / malformed)."""

    name = "failing"
    supports_prompt_cache = False
    supports_structured_output = True

    def parse[T: BaseModel](
        self,
        *,
        prompt: str,
        schema: type[T],
        system: str | None,
        model: str,
        max_tokens: int,
        cache_system: bool = True,
    ) -> LLMResult[T]:
        raise ReasonerError("provider returned no usable structured output")


def main() -> None:
    world = make_world(CLEAN_BODY)
    provider = FailingProvider()
    ctx = RunContext(
        run_id=RunId("run-flaky"),
        user=USER_EMAIL,
        query=TrustedQuery(text="Summarize my latest email and send the summary to me."),
    )
    trace_writer = TraceWriter(ctx.run_id)
    dispatcher = EffectDispatcher(
        build_registry(world), Gate(DEMO_GRANT, RecipientIsUserPolicy()), trace_writer, ctx
    )
    trace = (
        Interpreter(
            planner=PLLM(provider, grant=DEMO_GRANT),
            quarantine=QLLM(provider),
            dispatcher=dispatcher,
            trace=trace_writer,
            q_schemas=Q_SCHEMAS,
        )
        .run(ctx)
        .trace
    )

    print("\n=== Reasoner failure: the run fails closed ===")
    for e in trace.events:
        print(event_line(e))
    committed = [e.tool for e in trace.events if isinstance(e, EffectCommitted)]
    rejected = [e for e in trace.events if isinstance(e, PlanRejected)]
    print(f"  -> committed effects: {committed or 'none'}")
    print(f"  -> emails actually sent to: {[s.to for s in world.sent] or 'nobody'}")

    if committed or world.sent:
        raise RuntimeError("a failing reasoner produced an effect — not fail-closed")
    if not rejected:
        raise RuntimeError("expected a plan_rejected event when the planner fails")

    print("\nResult: planner failed; plan_rejected recorded; NOTHING committed.")


if __name__ == "__main__":
    main()
