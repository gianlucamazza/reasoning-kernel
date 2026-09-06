"""Run bounds for the Conductor (the §7 "termination" responsibility).

Plans are already finite acyclic DAGs (the Plan validator forbids cycles and forward refs), so the
risk is not infinite loops but an oversized or expensive plan from a real model. ``RunLimits`` caps
that. All fields default to ``None`` (unbounded) — so the deterministic test suite never touches the
wall clock and existing behaviour is unchanged unless a limit is set.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunLimits(BaseModel):
    """Root-wide budgets shared with all descendants. ``None`` means unbounded."""

    model_config = ConfigDict(frozen=True)

    max_steps: int | None = Field(default=None, ge=0)
    max_effects: int | None = Field(default=None, ge=0)
    max_q_parses: int | None = Field(default=None, ge=0)
    max_llm_calls: int | None = Field(default=None, ge=0)
    max_depth: int | None = Field(default=None, ge=0)
    reasoner_timeout_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @classmethod
    def operational(cls) -> RunLimits:
        """Bounded defaults for an operational session; all budgets span its descendants."""
        return cls(
            max_steps=256,
            max_effects=32,
            max_q_parses=16,
            max_llm_calls=32,
            max_depth=3,
            reasoner_timeout_s=60,
        )
