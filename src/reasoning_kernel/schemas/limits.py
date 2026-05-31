"""Run bounds for the Conductor (the §7 "termination" responsibility).

Plans are already finite acyclic DAGs (the Plan validator forbids cycles and forward refs), so the
risk is not infinite loops but an oversized or expensive plan from a real model. ``RunLimits`` caps
that. All fields default to ``None`` (unbounded) — so the deterministic test suite never touches the
wall clock and existing behaviour is unchanged unless a limit is set.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RunLimits(BaseModel):
    """Per-run bounds enforced by the Interpreter. ``None`` means unbounded."""

    model_config = ConfigDict(frozen=True)

    max_steps: int | None = None  # total plan steps
    max_effects: int | None = None  # ToolCallSteps actually dispatched
    max_q_parses: int | None = None  # quarantined parses
    max_depth: int | None = None  # nested sub-kernel depth (recursion bound)
    reasoner_timeout_s: float | None = None  # wall-clock per reasoner call
