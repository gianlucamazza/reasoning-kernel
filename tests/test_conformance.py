"""The operational profile is fixed, redacted and runnable outside pytest."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from types import ModuleType

import pytest

from reasoning_kernel.conformance import (
    GATE_V1_KINDS,
    OPERATIONAL_V1_KINDS,
    ConformanceConfigurationError,
    ConformanceObservation,
    ConformanceScenario,
    ConformanceSuite,
    ScenarioKind,
    run_conformance,
)
from reasoning_kernel.conformance.cli import main
from reasoning_kernel.conformance.reference import reference_suite


def _replace_scenario(
    suite: ConformanceSuite,
    kind: ScenarioKind,
    run,
) -> ConformanceSuite:
    return replace(
        suite,
        scenarios=tuple(
            ConformanceScenario(scenario.kind, run) if scenario.kind == kind else scenario
            for scenario in suite.scenarios
        ),
    )


def _gate_suite(
    overrides: dict[ScenarioKind, ConformanceObservation] | None = None,
) -> ConformanceSuite:
    observations = {
        kind: ConformanceObservation(
            decision_allowed=kind == ScenarioKind.GATE_AUTHORIZED,
            decision_enforced=kind != ScenarioKind.GATE_AUTHORIZED,
            audit_recorded=True,
        )
        for kind in GATE_V1_KINDS
    }
    observations.update(overrides or {})
    return ConformanceSuite(
        name="gate-reference",
        profile="gate-v1",
        scenarios=tuple(
            ConformanceScenario(kind, lambda observation=observations[kind]: observation)
            for kind in GATE_V1_KINDS
        ),
    )


def test_reference_suite_passes_complete_profile() -> None:
    report = run_conformance(reference_suite())

    assert report.passed
    assert [case.kind for case in report.cases] == list(OPERATIONAL_V1_KINDS)
    assert {case.outcome for case in report.cases} == {"pass"}


def test_gate_profile_passes_and_is_distinct_from_operational_profile() -> None:
    report = run_conformance(_gate_suite())

    assert report.passed
    assert report.profile == "gate-v1"
    assert [case.kind for case in report.cases] == list(GATE_V1_KINDS)


@pytest.mark.parametrize(
    ("kind", "observation", "check"),
    [
        (
            ScenarioKind.GATE_AUTHORIZED,
            ConformanceObservation(
                decision_allowed=False, decision_enforced=True, audit_recorded=True
            ),
            "authorized_gate_decision_missing",
        ),
        (
            ScenarioKind.GATE_CAPABILITY_DENIED,
            ConformanceObservation(
                decision_allowed=False, decision_enforced=False, audit_recorded=True
            ),
            "denied_gate_decision_not_enforced",
        ),
        (
            ScenarioKind.GATE_TAINTED_EGRESS_DENIED,
            ConformanceObservation(
                decision_allowed=False,
                decision_enforced=True,
                audit_recorded=True,
                subsequent_effects=1,
            ),
            "pipeline_ran_after_gate_denial",
        ),
        (
            ScenarioKind.GATE_INTERNAL_ERROR_DENIED,
            ConformanceObservation(decision_allowed=False, decision_enforced=True),
            "gate_audit_evidence_missing",
        ),
    ],
)
def test_gate_profile_rejects_invalid_evidence(kind, observation, check) -> None:
    report = run_conformance(_gate_suite({kind: observation}))

    case = next(item for item in report.cases if item.kind == kind)
    assert case.outcome == "fail"
    assert check in case.checks


def test_suite_rejects_missing_and_duplicate_scenarios() -> None:
    suite = reference_suite()
    with pytest.raises(ConformanceConfigurationError, match="complete"):
        run_conformance(replace(suite, scenarios=suite.scenarios[:-1]))
    with pytest.raises(ConformanceConfigurationError, match="duplicate"):
        run_conformance(replace(suite, scenarios=(*suite.scenarios, suite.scenarios[0])))


@pytest.mark.parametrize("name", ["", "host/path", "host name", "x" * 65])
def test_suite_name_is_a_payload_free_identifier(name) -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        ConformanceSuite(name=name, scenarios=())


@pytest.mark.parametrize(
    ("kind", "mutation", "check"),
    [
        (
            ScenarioKind.INJECTED_EGRESS,
            lambda observation: replace(observation, unauthorized_effects=1),
            "unauthorized_external_effect",
        ),
        (
            ScenarioKind.INVALID_OUTPUT,
            lambda observation: replace(observation, subsequent_effects=1),
            "execution_continued_after_invalid_output",
        ),
        (
            ScenarioKind.TOOL_FAILURE_BEFORE_EFFECT,
            lambda observation: replace(observation, authorized_effects=1),
            "effect_observed_before_failure",
        ),
        (
            ScenarioKind.AUDIT_FAILURE_BEFORE_DISPATCH,
            lambda observation: replace(observation, authorized_effects=1),
            "effect_ran_after_audit_failure",
        ),
        (
            ScenarioKind.CRASH_REOPEN_NO_REPLAY,
            lambda observation: replace(observation, replay_refused=False),
            "run_replay_not_refused",
        ),
    ],
)
def test_profile_rejects_host_observation_mutants(kind, mutation, check) -> None:
    suite = reference_suite()
    scenario = next(item for item in suite.scenarios if item.kind == kind)
    observation = mutation(scenario.run())
    report = run_conformance(_replace_scenario(suite, kind, lambda: observation))

    case = next(item for item in report.cases if item.kind == kind)
    assert case.outcome == "fail"
    assert check in case.checks


def test_profile_rejects_effect_without_prior_gate() -> None:
    suite = reference_suite()
    scenario = next(item for item in suite.scenarios if item.kind == ScenarioKind.BENIGN_EFFECT)
    observation = scenario.run()
    assert observation.result is not None
    result = observation.result.model_copy(deep=True)
    result.trace.events = [event for event in result.trace.events if event.kind != "gate_decision"]
    for seq, event in enumerate(result.trace.events):
        event.seq = seq
    mutated = replace(observation, result=result)

    report = run_conformance(_replace_scenario(suite, ScenarioKind.BENIGN_EFFECT, lambda: mutated))
    case = report.cases[0]
    assert case.outcome == "fail"
    assert "effect_without_prior_authorization" in case.checks


@pytest.mark.parametrize(
    "kind",
    [
        ScenarioKind.INJECTED_EGRESS,
        ScenarioKind.CAPABILITY_DENIED,
        ScenarioKind.AUDIT_FAILURE_BEFORE_DISPATCH,
    ],
)
def test_profile_rejects_effects_after_stop(kind) -> None:
    suite = reference_suite()
    scenario = next(item for item in suite.scenarios if item.kind == kind)
    observation = replace(scenario.run(), subsequent_effects=1)
    report = run_conformance(_replace_scenario(suite, kind, lambda: observation))
    case = next(item for item in report.cases if item.kind == kind)
    assert case.outcome == "fail"
    assert "execution_continued_after_stop" in case.checks


def test_profile_rejects_completed_effect_with_empty_trace() -> None:
    suite = reference_suite()
    observation = suite.scenarios[0].run()
    assert observation.result is not None
    observation.result.trace.events.clear()
    report = run_conformance(
        _replace_scenario(suite, ScenarioKind.BENIGN_EFFECT, lambda: observation)
    )
    assert report.cases[0].outcome == "fail"
    assert "effect_outcome_without_start" in report.cases[0].checks


def test_scenario_exception_is_inconclusive_and_redacted() -> None:
    def fail() -> ConformanceObservation:
        raise RuntimeError("SECRET injected prompt and /private/path")

    report = run_conformance(_replace_scenario(reference_suite(), ScenarioKind.BENIGN_EFFECT, fail))
    rendered = report.model_dump_json()

    assert not report.passed
    assert report.cases[0].outcome == "inconclusive"
    assert report.cases[0].checks == ["scenario_execution_error"]
    assert "SECRET" not in rendered
    assert "/private/path" not in rendered


def test_cli_writes_report_and_uses_documented_exit_codes(tmp_path, monkeypatch, capsys) -> None:
    module = ModuleType("host_conformance_fixture")
    module.build_suite = reference_suite
    module.build_failing_suite = lambda: _replace_scenario(
        reference_suite(),
        ScenarioKind.BENIGN_EFFECT,
        lambda: ConformanceObservation(unauthorized_effects=1),
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    report_path = tmp_path / "report.json"

    assert main([f"{module.__name__}:build_suite", "--output", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["schema_version"] == 1
    assert report["profile"] == "operational-v1"
    assert report["passed"] is True
    assert "PASS operational-v1" in capsys.readouterr().out

    assert main([f"{module.__name__}:build_failing_suite", "--output", str(report_path)]) == 1
    assert json.loads(report_path.read_text())["passed"] is False
    assert "FAIL operational-v1" in capsys.readouterr().out

    assert main(["invalid-reference"]) == 2
    assert "configuration or runner error" in capsys.readouterr().err


@pytest.mark.parametrize(
    "mutation,check",
    [
        ("missing_start", "effect_outcome_without_start"),
        ("missing_completion", "effect_outcome_mismatch"),
        ("missing_outcome", "effect_outcome_missing"),
        ("duplicate_gate", "duplicate_gate_decision"),
        ("duplicate_start", "duplicate_effect_start"),
        ("duplicate_completion", "duplicate_effect_completion"),
        ("duplicate_outcome", "duplicate_effect_outcome"),
        ("missing_invocation", "invocation_id_missing"),
        ("wrong_gate_run", "effect_identity_mismatch"),
        ("wrong_completion_tool", "effect_identity_mismatch"),
        ("wrong_completion_parent", "effect_identity_mismatch"),
        ("wrong_outcome_step", "effect_outcome_identity_mismatch"),
        ("wrong_outcome_status", "effect_outcome_mismatch"),
        ("wrong_output_validity", "effect_outcome_mismatch"),
        ("missing_output_validity", "effect_output_validity_missing"),
        ("completion_before_start", "effect_completion_without_start"),
        ("missing_terminal", "root_terminal_mismatch"),
        ("wrong_terminal", "root_terminal_mismatch"),
        ("duplicate_terminal", "root_terminal_mismatch"),
        ("foreign_terminal", "root_terminal_mismatch"),
        ("event_after_terminal", "root_terminal_mismatch"),
    ],
)
def test_profile_rejects_inconsistent_effect_evidence(mutation, check):
    suite = reference_suite()
    observation = suite.scenarios[0].run()
    result = observation.result
    assert result is not None
    events = result.trace.events
    gate = next(e for e in events if e.kind == "gate_decision")
    start = next(e for e in events if e.kind == "effect_started")
    completion = next(e for e in events if e.kind == "effect_committed")
    terminal = events[-1]
    outcome = result.effects[0]
    if mutation == "missing_start":
        events.remove(start)
    elif mutation == "missing_completion":
        events.remove(completion)
    elif mutation == "missing_outcome":
        result.effects.clear()
    elif mutation.startswith("duplicate_"):
        targets = {"gate": gate, "start": start, "completion": completion, "terminal": terminal}
        suffix = mutation.removeprefix("duplicate_")
        if suffix == "outcome":
            result.effects.append(outcome.model_copy(deep=True))
        else:
            target = targets[suffix]
            events.insert(events.index(target) + 1, target.model_copy(deep=True))
    elif mutation == "missing_invocation":
        start.invocation_id = None
    elif mutation == "wrong_gate_run":
        gate.run_id = "foreign"
    elif mutation == "wrong_completion_tool":
        completion.metadata["tool"] = "foreign"
    elif mutation == "wrong_completion_parent":
        completion.parent_run_id = "foreign"
    elif mutation == "wrong_outcome_step":
        outcome.step_id = "foreign"
    elif mutation == "wrong_outcome_status":
        outcome.status = "uncertain"
    elif mutation == "wrong_output_validity":
        outcome.output_valid = False
    elif mutation == "missing_output_validity":
        del completion.metadata["output_valid"]
    elif mutation == "completion_before_start":
        events.remove(completion)
        events.insert(events.index(start), completion)
    elif mutation == "missing_terminal":
        events.remove(terminal)
    elif mutation == "wrong_terminal":
        terminal.kind = "run_blocked"
    elif mutation == "foreign_terminal":
        terminal.run_id = "foreign"
    elif mutation == "event_after_terminal":
        events.append(events[0].model_copy(deep=True))
    for seq, event in enumerate(events):
        event.seq = seq
    report = run_conformance(
        _replace_scenario(suite, ScenarioKind.BENIGN_EFFECT, lambda: observation)
    )
    assert report.cases[0].outcome == "fail"
    assert check in report.cases[0].checks
