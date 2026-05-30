"""The Verifier's vocabulary: a run's trusted context, a verdict, and the declassify hook.

``DeclassPolicy`` is the single, auditable seam where tainted data is allowed to cross into a
WRITE effect. It is a deterministic predicate — never an LLM — and (per the paper) it should
compare against *trusted* (USER_QUERY) values only, never against substrings of tainted text.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.values import TaintedValue


class RunContext(BaseModel):
    """Trusted, controlled facts about a run — available to the Verifier and declassifier."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
    user: str  # the trusted requesting identity (e.g. the user's own email)
    query: str  # the controlled user query (the only thing the P-LLM ever sees)


class VerifierVerdict(BaseModel):
    """The outcome of a verification check."""

    allowed: bool
    reason: str
    issues: list[str] = Field(default_factory=list)


class DeclassPolicy(Protocol):
    """Decides whether tainted arguments may flow into a WRITE effect. Deterministic."""

    def may_declassify(
        self,
        tool: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> VerifierVerdict: ...
