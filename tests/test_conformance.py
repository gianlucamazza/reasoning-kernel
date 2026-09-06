"""The operational profile is fixed, redacted and runnable outside pytest."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from types import ModuleType

import pytest

from reasoning_kernel.conformance import (
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


def test_reference_suite_passes_complete_profile() -> None:
    report = run_conformance(reference_suite())

    assert report.passed
    assert [case.kind for case in report.cases] == list(OPERATIONAL_V1_KINDS)
    assert {case.outcome for case in report.cases} == {"pass"}


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
    monkeypatch.setitem(sys.modules, module.__name__, module)
    report_path = tmp_path / "report.json"

    assert main([f"{module.__name__}:build_suite", "--output", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["schema_version"] == 1
    assert report["profile"] == "operational-v1"
    assert report["passed"] is True
    assert "PASS operational-v1" in capsys.readouterr().out

    assert main(["invalid-reference"]) == 2
    assert "configuration or runner error" in capsys.readouterr().err
