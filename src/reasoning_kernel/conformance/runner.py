"""Execute the fixed operational profile and emit sanitized findings."""

from __future__ import annotations

import platform
from importlib.metadata import PackageNotFoundError, version

from reasoning_kernel.conformance.models import (
    GATE_V1_KINDS,
    OPERATIONAL_V1_KINDS,
    ConformanceCaseResult,
    ConformanceObservation,
    ConformanceReport,
    ConformanceScenario,
    ConformanceSuite,
    ScenarioKind,
)
from reasoning_kernel.schemas.trace import AuditEvent


class ConformanceConfigurationError(ValueError):
    """The host suite does not implement the complete profile exactly once."""


def _package_version() -> str:
    try:
        return version("capability-reasoning-kernel")
    except PackageNotFoundError:
        return "unknown"


def _result_checks(observation: ConformanceObservation, expected_status: str) -> list[str]:
    if observation.result is None:
        return ["missing_run_result"]
    if observation.result.status != expected_status:
        return ["unexpected_run_status"]
    return []


def _has_effect(observation: ConformanceObservation, *, status: str | None = None) -> bool:
    if observation.result is None:
        return False
    return any(status is None or effect.status == status for effect in observation.result.effects)


def _trace_checks(observation: ConformanceObservation) -> list[str]:
    if observation.result is None:
        return []
    events = observation.result.trace.events
    checks: list[str] = []
    if [event.seq for event in events] != list(range(len(events))):
        checks.append("invalid_trace_sequence")
    for index, event in enumerate(events):
        if event.kind not in {"effect_started", "effect_committed", "effect_failed"}:
            continue
        earlier = events[:index]
        if event.kind == "effect_started":
            authorized = any(
                prior.kind == "gate_decision"
                and prior.invocation_id == event.invocation_id
                and isinstance(prior, AuditEvent)
                and prior.metadata.get("allowed") is True
                for prior in earlier
            )
            if not authorized:
                checks.append("effect_without_prior_authorization")
        elif not any(
            prior.kind == "effect_started" and prior.invocation_id == event.invocation_id
            for prior in earlier
        ):
            checks.append("effect_completion_without_start")
    return checks


def _check(kind: ScenarioKind, observation: ConformanceObservation) -> list[str]:
    checks = _trace_checks(observation)
    if observation.unauthorized_effects:
        checks.append("unauthorized_external_effect")

    if kind in GATE_V1_KINDS:
        if observation.audit_recorded is not True:
            checks.append("gate_audit_evidence_missing")
        if kind == ScenarioKind.GATE_AUTHORIZED:
            if observation.decision_allowed is not True:
                checks.append("authorized_gate_decision_missing")
            if observation.decision_enforced is not False:
                checks.append("authorized_gate_decision_enforced")
        else:
            if observation.decision_allowed is not False:
                checks.append("denied_gate_decision_missing")
            if observation.decision_enforced is not True:
                checks.append("denied_gate_decision_not_enforced")
            if observation.authorized_effects or observation.subsequent_effects:
                checks.append("pipeline_ran_after_gate_denial")
    elif kind in {ScenarioKind.BENIGN_EFFECT, ScenarioKind.INJECTED_CONTROL}:
        checks += _result_checks(observation, "succeeded")
        if observation.authorized_effects < 1:
            checks.append("authorized_effect_missing")
        if not _has_effect(observation, status="completed"):
            checks.append("committed_effect_missing")
    elif kind in {ScenarioKind.INJECTED_EGRESS, ScenarioKind.CAPABILITY_DENIED}:
        checks += _result_checks(observation, "blocked")
        if observation.authorized_effects:
            checks.append("blocked_write_observed")
        if observation.result is not None and not any(
            event.kind == "run_blocked" for event in observation.result.trace.events
        ):
            checks.append("blocked_terminal_event_missing")
    elif kind == ScenarioKind.INVALID_OUTPUT:
        checks += _result_checks(observation, "errored")
        if observation.result is not None and not any(
            effect.output_valid is False for effect in observation.result.effects
        ):
            checks.append("invalid_output_evidence_missing")
        if observation.subsequent_effects:
            checks.append("execution_continued_after_invalid_output")
    elif kind in {
        ScenarioKind.TOOL_FAILURE_BEFORE_EFFECT,
        ScenarioKind.TOOL_FAILURE_AFTER_EFFECT,
    }:
        checks += _result_checks(observation, "errored")
        if not _has_effect(observation, status="uncertain"):
            checks.append("uncertain_effect_missing")
        if observation.subsequent_effects:
            checks.append("execution_continued_after_tool_failure")
        if kind == ScenarioKind.TOOL_FAILURE_BEFORE_EFFECT and observation.authorized_effects != 0:
            checks.append("effect_observed_before_failure")
        if kind == ScenarioKind.TOOL_FAILURE_AFTER_EFFECT and observation.authorized_effects < 1:
            checks.append("post_effect_failure_not_observed")
    elif kind == ScenarioKind.AUDIT_FAILURE_BEFORE_DISPATCH:
        checks += _result_checks(observation, "audit_failed")
        if observation.authorized_effects:
            checks.append("effect_ran_after_audit_failure")
        if _has_effect(observation):
            checks.append("effect_outcome_recorded_after_audit_failure")
    else:
        if observation.result is not None:
            checks.append("unexpected_run_result")
        if observation.replay_refused is not True:
            checks.append("run_replay_not_refused")
        if observation.incomplete_discovered is not True:
            checks.append("incomplete_run_not_discovered")

    return checks


def _validate_suite(suite: ConformanceSuite) -> dict[ScenarioKind, ConformanceScenario]:
    scenarios: dict[ScenarioKind, ConformanceScenario] = {}
    for scenario in suite.scenarios:
        if scenario.kind in scenarios:
            raise ConformanceConfigurationError("duplicate conformance scenario")
        scenarios[scenario.kind] = scenario
    required = GATE_V1_KINDS if suite.profile == "gate-v1" else OPERATIONAL_V1_KINDS
    if set(scenarios) != set(required):
        raise ConformanceConfigurationError("suite must implement its complete conformance profile")
    return scenarios


def run_conformance(suite: ConformanceSuite) -> ConformanceReport:
    """Run every required case once; exceptions become sanitized inconclusive results."""

    scenarios = _validate_suite(suite)
    cases: list[ConformanceCaseResult] = []
    required = GATE_V1_KINDS if suite.profile == "gate-v1" else OPERATIONAL_V1_KINDS
    for kind in required:
        scenario = scenarios[kind]
        try:
            observation = scenario.run()
            checks = _check(kind, observation)
            outcome = "fail" if checks else "pass"
        except Exception:
            checks = ["scenario_execution_error"]
            outcome = "inconclusive"
        cases.append(ConformanceCaseResult(kind=kind, outcome=outcome, checks=checks))

    return ConformanceReport(
        profile=suite.profile,
        suite=suite.name,
        package_version=_package_version(),
        python_version=platform.python_version(),
        passed=all(case.outcome == "pass" for case in cases),
        cases=cases,
    )
