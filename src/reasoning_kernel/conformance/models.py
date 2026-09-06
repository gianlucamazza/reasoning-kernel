"""Public contracts for executable host conformance evidence."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reasoning_kernel.schemas.trace import RunResult


class ScenarioKind(StrEnum):
    """Required cases in the versioned operational conformance profile."""

    BENIGN_EFFECT = "benign_effect"
    INJECTED_CONTROL = "injected_control"
    INJECTED_EGRESS = "injected_egress"
    CAPABILITY_DENIED = "capability_denied"
    INVALID_OUTPUT = "invalid_output"
    TOOL_FAILURE_BEFORE_EFFECT = "tool_failure_before_effect"
    TOOL_FAILURE_AFTER_EFFECT = "tool_failure_after_effect"
    AUDIT_FAILURE_BEFORE_DISPATCH = "audit_failure_before_dispatch"
    CRASH_REOPEN_NO_REPLAY = "crash_reopen_no_replay"


OPERATIONAL_V1_KINDS = tuple(ScenarioKind)


@dataclass(frozen=True, slots=True)
class ConformanceObservation:
    """Evidence returned by trusted host code for one isolated scenario.

    Effect counts cover externally visible WRITE effects, not READ calls. The
    kernel deliberately cannot infer external state from its own trace.
    """

    result: RunResult | None = None
    authorized_effects: int = 0
    unauthorized_effects: int = 0
    subsequent_effects: int = 0
    replay_refused: bool | None = None
    incomplete_discovered: bool | None = None

    def __post_init__(self) -> None:
        if min(self.authorized_effects, self.unauthorized_effects, self.subsequent_effects) < 0:
            raise ValueError("effect counts cannot be negative")


@dataclass(frozen=True, slots=True)
class ConformanceScenario:
    """A required scenario and the trusted host factory that executes it."""

    kind: ScenarioKind
    run: Callable[[], ConformanceObservation]


@dataclass(frozen=True, slots=True)
class ConformanceSuite:
    """One host target implementing the complete ``operational-v1`` profile."""

    name: str
    scenarios: tuple[ConformanceScenario, ...]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.name) is None:
            raise ValueError("suite name must be a safe identifier")


class ConformanceCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ScenarioKind
    outcome: Literal["pass", "fail", "inconclusive"]
    checks: list[str] = Field(default_factory=list)


class ConformanceReport(BaseModel):
    """Payload-free, machine-readable result of one conformance run."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    profile: Literal["operational-v1"] = "operational-v1"
    suite: str
    package_version: str
    python_version: str
    passed: bool
    cases: list[ConformanceCaseResult]
