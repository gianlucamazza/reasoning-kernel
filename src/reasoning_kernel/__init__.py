"""Reasoning Kernel — a reference implementation of the Reasoning Kernel pattern (CaMeL-like form).

Treat every LLM as untrusted compute: control its input (assembled context, Invariant A) and verify
its output (a deterministic Gate, Invariant B). This module re-exports the building blocks an
integrator wires together — see the README's "Embedding the kernel" section and
``reasoning_kernel.demo.email_exfil`` for a complete worked example.
"""

from __future__ import annotations

from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import LLMProvider, ReasonerError
from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import Capability, CapabilitySet, EffectLevel
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.plan import (
    ArgRef,
    ConstStep,
    MergeStep,
    Plan,
    QuarantineParseStep,
    SubKernelStep,
    ToolCallStep,
)
from reasoning_kernel.schemas.policy import (
    DeclassPolicy,
    RunContext,
    TrustedQuery,
    VerifierVerdict,
)
from reasoning_kernel.schemas.provenance import DataSubject, ProvenanceLabel, Source
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.trace import RunResult, RunTrace
from reasoning_kernel.schemas.values import TaintedValue
from reasoning_kernel.tools.registry import ToolRegistry

__all__ = [
    "PLLM",
    "QLLM",
    "ArgRef",
    "Capability",
    "CapabilitySet",
    "ConstStep",
    "DataSubject",
    "DeclassPolicy",
    "EffectDispatcher",
    "EffectLevel",
    "FakeProvider",
    "Gate",
    "Interpreter",
    "LLMProvider",
    "MergeStep",
    "Plan",
    "ProvenanceLabel",
    "QuarantineParseStep",
    "ReasonerError",
    "RunContext",
    "RunId",
    "RunLimits",
    "RunResult",
    "RunTrace",
    "Source",
    "StepId",
    "SubKernelStep",
    "TaintedValue",
    "ToolCallStep",
    "ToolRegistry",
    "ToolSpec",
    "TraceWriter",
    "TrustedQuery",
    "VerifierVerdict",
    "default_model_for",
    "get_llm_provider",
]
