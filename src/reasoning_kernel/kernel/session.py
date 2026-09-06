"""Operational embedding entry point: one context, one catalog, one run, one audit sink."""

from __future__ import annotations

from pydantic import BaseModel

from reasoning_kernel.kernel.effects import EffectDispatcher
from reasoning_kernel.kernel.gate import Gate
from reasoning_kernel.kernel.interpreter import Interpreter
from reasoning_kernel.kernel.runtime import ReasonerExecutor
from reasoning_kernel.memory.sink import TraceSink
from reasoning_kernel.memory.trace import TraceWriter
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import CapabilitySet
from reasoning_kernel.schemas.limits import RunLimits
from reasoning_kernel.schemas.policy import DeclassPolicy, RunContext
from reasoning_kernel.schemas.trace import RunResult
from reasoning_kernel.tools.registry import ToolRegistry


class RunSession:
    """Single-use session. The host authorizes providers, tools, policy and identity.

    Supply SQLiteTraceSink for durability (MemoryTraceSink is useful in tests). Tool adapters
    must bound their own I/O and must not retry ambiguous external writes automatically.
    """

    def __init__(
        self,
        *,
        ctx: RunContext,
        registry: ToolRegistry,
        grant: CapabilitySet,
        declass: DeclassPolicy,
        planner: PLLM,
        quarantine: QLLM,
        q_schemas: dict[str, type[BaseModel]],
        sink: TraceSink,
        limits: RunLimits | None = None,
        executor: ReasonerExecutor | None = None,
    ) -> None:
        registry = registry.snapshot()
        for spec in registry.catalog():
            if spec.args_leave_boundary is None:
                raise ValueError(f"tool {spec.name!r} must declare args_leave_boundary")
        if not planner.grant.is_subset_of(grant):
            raise ValueError("planner grant exceeds session grant")
        self._ctx = ctx.model_copy(deep=True)
        trace = TraceWriter(ctx.run_id, sink=sink, operational=True)
        self._interpreter = Interpreter(
            planner=planner,
            quarantine=quarantine,
            dispatcher=EffectDispatcher(registry, Gate(grant, declass), trace, self._ctx),
            trace=trace,
            q_schemas=q_schemas,
            limits=limits if limits is not None else RunLimits.operational(),
            executor=executor,
        )

    def run(self) -> RunResult:
        return self._interpreter.run(self._ctx)
