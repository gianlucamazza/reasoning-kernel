# Operational embedding and migration (0.5 candidate)

`RunSession` is the bounded, single-use entry point. The host supplies authenticated identity, a
trusted query, a fixed grant, deterministic policy, schemas and adapters. Authentication, scheduling,
transactions, external-effect reconciliation and provider authorization remain host responsibilities.

## Example

This runnable example uses only the deterministic demo adapters. Replace them with host-owned
adapters after verifying their I/O timeouts, destination restrictions and provenance.

```python
from reasoning_kernel import (
    FakeProvider, PLLM, QLLM, RunContext, RunId, RunSession, SQLiteTraceSink, TrustedQuery,
)
from reasoning_kernel.demo.email_exfil import CLEAN_BODY, benign_plan, make_world
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT, Q_SCHEMAS, EmailSummary, RecipientIsUserPolicy, build_registry,
)

ctx = RunContext(run_id=RunId("unique-host-request-id"), user="user@example.com",
                 query=TrustedQuery(text="Summarize my latest email and send it to me"))
provider = FakeProvider({"Plan": benign_plan(ctx.run_id), "EmailSummary": EmailSummary(text="OK")})
with SQLiteTraceSink("audit.sqlite") as sink:
    session = RunSession(
        ctx=ctx, registry=build_registry(make_world(CLEAN_BODY)), grant=DEMO_GRANT,
        declass=RecipientIsUserPolicy(), planner=PLLM(provider, grant=DEMO_GRANT),
        quarantine=QLLM(provider), q_schemas=Q_SCHEMAS, sink=sink,
    )
    result = session.run()
    print(result.status, [(e.tool, e.status) for e in result.effects])
```

Use a unique root run ID per host request. The sink refuses reuse even after a crash. Do not substitute
a new ID to retry an ambiguous request: reconcile external effects first. `MemoryTraceSink` provides
the same sequence/uniqueness checks only for its in-memory lifetime.

Separate sessions may share a sink. SQLite serializes access, including across connections/processes;
each session has its own context, store, catalog snapshot and budget. An interpreter/session cannot
be reused or invoked concurrently. The host must make shared adapters, policies and provider clients
thread-safe or supply independent instances. Schema classes and callables are trusted host code;
do not mutate them while sessions execute.

## Budgets and timeouts

| Limit | Session default | Accounting |
|---|---:|---|
| `max_steps` | 256 | Reserve each accepted plan before executing any of its steps |
| `max_effects` | 32 | Tool-step attempts, including READs and denied/invalid attempts |
| `max_q_parses` | 16 | Quarantined parse attempts |
| `max_llm_calls` | 32 | Planner/parser invocations across the run tree |
| `max_depth` | 3 | Root depth is zero |
| `reasoner_timeout_s` | 60 | Maximum wait for each planner/parser invocation |

All descendants share counters, including siblings. Exhausted child budgets abort ancestors. `None`
disables a limit; zero is valid for counters, but timeouts must be finite and positive. Low-level
`RunLimits()` remains unbounded; `RunLimits.operational()` supplies the defaults above.

LLM invocation counts are not monetary or HTTP-request budgets: an invocation can include one schema
fallback and SDK transport retries. Returned usage metrics cover successfully parsed responses;
abandoned calls, fallback failures and retries can incur additional costs. Do not use them as billing.

The shared `ReasonerExecutor` admits eight active calls with no waiting queue. A timed-out call keeps
its slot until it really finishes; it cannot emit late trace events or invoke tools. Capacity exhaustion
aborts new work. Hosts can inject an executor and call `close()` on shutdown. Python cannot kill these
threads, and a hung call can delay process exit. Configure SDK/network timeouts and supervise the host.

Tool adapters run synchronously and **must enforce their own I/O timeouts**. The kernel does not claim
that a thread timeout cancels a remote write. Adapter errors after sending a request are uncertain and
must not cause automatic retries.

## Effect contracts and trust

Operational `ToolSpec` registrations must explicitly declare `args_leave_boundary=True` for arguments
transmitted externally, including READ tools such as search or fetch. WRITE and egress tools require
capabilities and provenance verification. `False` never disables WRITE checks. Legacy low-level READ
registrations may omit the declaration, retaining their old behavior.

Inputs are normalized once; the Gate inspects normalized arguments and the callable receives that
model. Changed/default fields conservatively inherit joined input/query provenance; unchanged fields
keep their labels. Validators and declassifiers must be deterministic and free of I/O. Returned values
must be instances of the declared output schema and pass revalidation. Invalid output stops subsequent
steps, but cannot undo external work already performed by the callable.

The root planner sees controlled input. Sub-planners deliberately see delegated untrusted content
under reduced grants; their literals inherit its provenance. Catalog filtering supports planning,
while the Gate remains authoritative. This is Python composition, not a sandbox against host code.
Capabilities are host-issued authority declarations, not cryptographic credentials.

LLM providers are data recipients too. Supplying a Q-LLM/sub-planner authorizes that provider to receive
the corresponding data. The tool Gate does not enforce provider confidentiality/retention; choose
approved endpoints per data class or use a local provider.

## Audit and recovery

Each invocation has its own ID, Gate decision, durable `effect_started` before the callable, and
`effect_committed` after it returns. Completion means a returned call, not a distributed transaction
or independently verified external success. Invalid output records `output_valid=False`; a raised
exception produces `effect_failed` and an uncertain external outcome.

`RunResult.status` is `succeeded`, `blocked`, `aborted`, `errored` or `audit_failed`. `committed` holds
only the final value: `None` never implies rollback. Inspect `effects` for completed/uncertain calls.
A storage failure after a callable returns leaves uncertainty because completion was not recorded.

SQLite uses WAL, FULL synchronous writes and a committed append per event. Authorization/start must
persist before the callable. Any append failure stops the run, returning `audit_failed` even when a
terminal event cannot be written. Reservation errors raise `TraceStorageError` before execution.
After a crash, `sink.read(run_id)` returns events, with no replay operation. A started invocation without
completion requires reconciliation against the external system. Missing terminal events require review.

Persistent events use `AuditEvent`, `schema_version=1`, root sequence, run/parent IDs, opaque step and
invocation IDs, tool/provenance metadata, error codes and returned LLM usage/latency. Prompts, plans,
payloads, content digests and raw exception messages are excluded. Host IDs, tool/capability names and
provider metadata must themselves contain no secrets. Model-chosen step IDs are replaced with opaque
IDs. Operational snapshots use the same redacted representation.

Low-level `TraceWriter` keeps detailed plans for demos. Snapshots are deep-detached, not immutable
objects. Detailed digests canonicalize JSON-like values, models and sets; unsupported objects are
rejected rather than represented with `repr`. Short digests are not security proofs.

Use a local filesystem for SQLite. The host owns file permissions, backups, encryption and retention,
including WAL files. This append-only API does not prevent database administrators from editing the
file and is not tamper-evident storage.

## Migration and verification

- Prefer `RunSession` with a sink and explicit egress declarations. Low-level wiring remains supported
  but now rejects context/trace mismatches and repeated execution of the same interpreter.
- Budget counters span descendants. Replace assumptions about per-child resets.
- Child IDs are opaque: use `parent_run_id`, `step_id` and `invocation_id`, not slash-splitting.
- Account for usage/start/failure events; the plan need not be the first event.
- Review normalization-sensitive policies, output model contracts and application retry logic.
- `LLMResult`, `LLMUsage`, `ToolExecutionError` and session/sink types are exported at the package root.

`just check` verifies lint, typing and coverage. `just package-check` checks wheel/sdist metadata and
installs the wheel outside the source tree to exercise public imports and the deterministic demo.
CI covers Python 3.12–3.14. Release tags must match package metadata. After tagged-commit checks,
release builds once, records hashes, publishes to TestPyPI, verifies served bytes, then promotes those
artifacts to PyPI. OIDC publishers/environments must be configured. These checks are distinct from
live provider and host-adapter acceptance.
