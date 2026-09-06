"""Reasoning Kernel — a reference implementation of the Reasoning Kernel pattern (CaMeL-like form).

Treat every LLM as untrusted compute: control its input (assembled context, Invariant A) and verify
its output (a deterministic Gate, Invariant B). This module re-exports the building blocks an
integrator wires together — see the README's "Embedding the kernel" section and
``reasoning_kernel.demo.email_exfil`` for a complete worked example.
"""

from __future__ import annotations

from reasoning_kernel.kernel.effects import EffectDispatcher, ToolExecutionError
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.kernel.runtime import ReasonerExecutor
from reasoning_kernel.kernel.session import RunSession
from reasoning_kernel.memory.sink import (
    MemoryTraceSink,
    SQLiteTraceSink,
    TraceSink,
    TraceStorageError,
)
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.base import (
    LLMProvider,
    LLMResult,
    LLMUsage,
    ReasonerError,
    TransportError,
)
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
from reasoning_kernel.schemas.trace import AuditEvent, EffectOutcome, RunResult, RunTrace
from reasoning_kernel.schemas.values import TaintedValue
from reasoning_kernel.tools.registry import ToolRegistry

__all__ = [
    "PLLM",
    "QLLM",
    "ArgRef",
    "AuditEvent",
    "Capability",
    "CapabilitySet",
    "ConstStep",
    "DataSubject",
    "DeclassPolicy",
    "EffectDispatcher",
    "EffectLevel",
    "EffectOutcome",
    "FakeProvider",
    "Gate",
    "Interpreter",
    "LLMProvider",
    "LLMResult",
    "LLMUsage",
    "MemoryTraceSink",
    "MergeStep",
    "Plan",
    "ProvenanceLabel",
    "QuarantineParseStep",
    "ReasonerError",
    "ReasonerExecutor",
    "RunContext",
    "RunId",
    "RunLimits",
    "RunResult",
    "RunSession",
    "RunTrace",
    "SQLiteTraceSink",
    "Source",
    "StepId",
    "SubKernelStep",
    "TaintedValue",
    "ToolCallStep",
    "ToolExecutionError",
    "ToolRegistry",
    "ToolSpec",
    "TraceSink",
    "TraceStorageError",
    "TraceWriter",
    "TransportError",
    "TrustedQuery",
    "VerifierVerdict",
    "default_model_for",
    "get_llm_provider",
]
