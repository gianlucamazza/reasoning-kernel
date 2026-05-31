"""The Plan IR — the only thing the Privileged planner (P-LLM) may emit.

A plan is a typed, forward-only DAG of steps, never prose and never code. Because the planner
is invoked through structured output against this schema, it *cannot* emit free text or call a
tool directly: it can only describe a plan the deterministic kernel will later check and run.
Steps reference earlier results by id via ``ArgRef`` (forward-only — enforced here).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from reasoning_kernel.schemas.ids import RunId, StepId


class ArgRef(BaseModel):
    """A reference to the value produced by an earlier step (optionally a field of it)."""

    kind: Literal["ref"] = "ref"
    ref: StepId
    path: str | None = None  # dotted access into a structured result, e.g. "summary.text"

    @model_validator(mode="after")
    def _validate_path(self) -> ArgRef:
        # Reject a malformed path at plan-validation time, not opaquely at navigation time. Only
        # structural malformation is rejected (empty / leading / trailing / doubled '.'); component
        # names are left free, since dict payload keys need not be identifiers.
        if self.path is not None and (self.path == "" or "" in self.path.split(".")):
            raise ValueError(
                f"malformed path {self.path!r}: empty component "
                "(no leading, trailing, or doubled '.')"
            )
        return self


# An argument is either a reference to a prior step or an inline trusted literal scalar.
ArgValue = ArgRef | str | int | float | bool | None


class ConstStep(BaseModel):
    """A trusted literal the planner injects (e.g. the requesting user's own address)."""

    kind: Literal["const"] = "const"
    id: StepId
    value: str | int | float | bool | None


class ToolCallStep(BaseModel):
    """Invoke a registered tool. The ONLY step kind that can reach a real-world effect."""

    kind: Literal["tool"] = "tool"
    id: StepId
    tool: str
    args: dict[str, ArgValue] = Field(default_factory=dict)


class QuarantineParseStep(BaseModel):
    """Hand an untrusted blob to the Q-LLM and get a typed value back. No tool access."""

    kind: Literal["q_parse"] = "q_parse"
    id: StepId
    source: ArgRef
    schema_ref: str  # name of the registered output schema the Q-LLM must produce
    instruction: str  # extraction instruction (data, never commands)


class SubKernelStep(BaseModel):
    """Delegate processing of an untrusted blob to an inner Reasoning Kernel (§5.4).

    The inner kernel runs at a REDUCED capability grant (clamped to a subset of the outer grant), so
    an injection in the blob is confined: it can only do what the reduced grant permits.
    """

    kind: Literal["subkernel"] = "subkernel"
    id: StepId
    source: ArgRef  # the untrusted content the sub-kernel reasons over
    instruction: str  # the (trusted) task, from the outer planner
    grant: list[str]  # capability names for the inner kernel (clamped to the outer grant)


class MergeStep(BaseModel):
    """Combine several earlier results into one structured value (the only value-COMBINING step).

    The result is a ``dict`` of the named inputs, labelled with the *join* of their labels — sources
    unioned (with ``DERIVED``), readers intersected, subjects unioned — so taint only ever increases
    (over-approximation, never laundering). Useful to hand a composite of several reads to a single
    Q-LLM parse or sub-kernel, which each take only one ``source``.
    """

    kind: Literal["merge"] = "merge"
    id: StepId
    inputs: dict[str, ArgRef]  # name -> reference; a merge combines results, never inline literals

    @model_validator(mode="after")
    def _non_empty(self) -> MergeStep:
        if not self.inputs:
            raise ValueError(f"merge step {self.id!r} has no inputs")
        return self


PlanStep = Annotated[
    ConstStep | ToolCallStep | QuarantineParseStep | SubKernelStep | MergeStep,
    Field(discriminator="kind"),
]


def _refs_of(
    step: ConstStep | ToolCallStep | QuarantineParseStep | SubKernelStep | MergeStep,
) -> list[StepId]:
    """The StepIds this step depends on."""
    if isinstance(step, ToolCallStep):
        return [a.ref for a in step.args.values() if isinstance(a, ArgRef)]
    if isinstance(step, QuarantineParseStep | SubKernelStep):
        return [step.source.ref]
    if isinstance(step, MergeStep):
        return [r.ref for r in step.inputs.values()]
    return []


class Plan(BaseModel):
    """A complete, validated plan: unique ids, forward-only refs, a resolvable final step."""

    run_id: RunId
    steps: list[PlanStep]
    final: StepId

    @model_validator(mode="after")
    def _validate_dag(self) -> Plan:
        seen: set[StepId] = set()
        for step in self.steps:
            for ref in _refs_of(step):
                if ref not in seen:
                    raise ValueError(
                        f"step {step.id!r} references {ref!r} which is not an earlier step"
                    )
            if step.id in seen:
                raise ValueError(f"duplicate step id {step.id!r}")
            seen.add(step.id)
        if self.final not in seen:
            raise ValueError(f"final step {self.final!r} is not among the plan steps")
        return self
