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


def _event_identity(event: AuditEvent) -> tuple[object, ...]:
    return (event.run_id, event.parent_run_id, event.step_id, event.metadata.get("tool"))


def _trace_checks(observation: ConformanceObservation) -> list[str]:
    result = observation.result
    if result is None:
        return []
    events = result.trace.events
    checks: list[str] = []
    if [event.seq for event in events] != list(range(len(events))):
        checks.append("invalid_trace_sequence")
    gates: dict[str, AuditEvent] = {}
    starts: dict[str, AuditEvent] = {}
    completions: dict[str, AuditEvent] = {}
    for event in events:
        if event.kind not in {
            "gate_decision",
            "effect_started",
            "effect_committed",
            "effect_failed",
        }:
            continue
        if not isinstance(event, AuditEvent):
            checks.append("operational_audit_event_missing")
            continue
        invocation = event.invocation_id
        if not invocation:
            checks.append("invocation_id_missing")
            continue
        if not isinstance(event.metadata.get("tool"), str) or not event.metadata["tool"]:
            checks.append("effect_tool_missing")
        if event.kind == "gate_decision":
            if invocation in gates:
                checks.append("duplicate_gate_decision")
            gates[invocation] = event
        elif event.kind == "effect_started":
            gate = gates.get(invocation)
            if gate is None or gate.metadata.get("allowed") is not True:
                checks.append("effect_without_prior_authorization")
            elif _event_identity(gate) != _event_identity(event):
                checks.append("effect_identity_mismatch")
            if invocation in starts:
                checks.append("duplicate_effect_start")
            starts[invocation] = event
        else:
            start = starts.get(invocation)
            if start is None:
                checks.append("effect_completion_without_start")
            elif _event_identity(start) != _event_identity(event):
                checks.append("effect_identity_mismatch")
            if invocation in completions:
                checks.append("duplicate_effect_completion")
            completions[invocation] = event
            if (
                event.kind == "effect_committed"
                and type(event.metadata.get("output_valid")) is not bool
            ):
                checks.append("effect_output_validity_missing")

    outcome_ids: set[str] = set()
    for effect in result.effects:
        invocation = effect.invocation_id
        if invocation in outcome_ids:
            checks.append("duplicate_effect_outcome")
        outcome_ids.add(invocation)
        start = starts.get(invocation)
        if start is None:
            checks.append("effect_outcome_without_start")
            continue
        if (effect.run_id, effect.step_id, effect.tool) != (
            start.run_id,
            start.step_id,
            start.metadata.get("tool"),
        ):
            checks.append("effect_outcome_identity_mismatch")
        completion = completions.get(invocation)
        committed = completion is not None and completion.kind == "effect_committed"
        expected_status = "completed" if committed else "uncertain"
        expected_validity = (
            completion.metadata.get("output_valid")
            if completion is not None and committed
            else None
        )
        if effect.status != expected_status or effect.output_valid is not expected_validity:
            checks.append("effect_outcome_mismatch")
        if completion is None and result.status != "audit_failed":
            checks.append("effect_completion_missing")
    if starts.keys() - outcome_ids:
        checks.append("effect_outcome_missing")

    terminal_kinds: dict[str, set[str]] = {
        "succeeded": {"run_committed"},
        "blocked": {"run_blocked"},
        "errored": {"run_errored", "plan_rejected"},
        "aborted": {"run_aborted"},
        "audit_failed": set(),
    }
    all_terminals = {kind for kinds in terminal_kinds.values() for kind in kinds}
    root_terminals = [
        event
        for event in events
        if event.run_id == result.trace.run_id and event.kind in all_terminals
    ]
    # A storage failure can prevent even the first event or terminal from being recorded.
    if result.status == "audit_failed":
        if root_terminals:
            checks.append("unexpected_root_terminal")
    elif (
        len(root_terminals) != 1
        or root_terminals[0].kind not in terminal_kinds[result.status]
        or root_terminals[0] is not events[-1]
        or root_terminals[0].parent_run_id is not None
    ):
        checks.append("root_terminal_mismatch")
    return list(dict.fromkeys(checks))


def _check(kind: ScenarioKind, observation: ConformanceObservation) -> list[str]:
    checks = _trace_checks(observation)
    if (
        kind
        in {
            ScenarioKind.INJECTED_EGRESS,
            ScenarioKind.CAPABILITY_DENIED,
            ScenarioKind.AUDIT_FAILURE_BEFORE_DISPATCH,
        }
        and observation.subsequent_effects
    ):
        checks.append("execution_continued_after_stop")
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
