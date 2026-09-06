"""Executable, versioned evidence that a host preserves the kernel's contracts."""

from reasoning_kernel.conformance.models import (
    OPERATIONAL_V1_KINDS,
    ConformanceCaseResult,
    ConformanceObservation,
    ConformanceReport,
    ConformanceScenario,
    ConformanceSuite,
    ScenarioKind,
)
from reasoning_kernel.conformance.runner import (
    ConformanceConfigurationError,
    run_conformance,
)

__all__ = [
    "OPERATIONAL_V1_KINDS",
    "ConformanceCaseResult",
    "ConformanceConfigurationError",
    "ConformanceObservation",
    "ConformanceReport",
    "ConformanceScenario",
    "ConformanceSuite",
    "ScenarioKind",
    "run_conformance",
]
