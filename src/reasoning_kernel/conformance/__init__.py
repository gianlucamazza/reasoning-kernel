"""Executable, versioned evidence that a host preserves the kernel's contracts."""

from reasoning_kernel.conformance.models import (
    GATE_V1_KINDS,
    OPERATIONAL_V1_KINDS,
    ConformanceCaseResult,
    ConformanceObservation,
    ConformanceProfile,
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
    "GATE_V1_KINDS",
    "OPERATIONAL_V1_KINDS",
    "ConformanceCaseResult",
    "ConformanceConfigurationError",
    "ConformanceObservation",
    "ConformanceProfile",
    "ConformanceReport",
    "ConformanceScenario",
    "ConformanceSuite",
    "ScenarioKind",
    "run_conformance",
]
