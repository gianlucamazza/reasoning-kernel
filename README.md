# Reasoning Kernel

A small, framework-agnostic Python reference implementation of the **Reasoning Kernel** pattern
in its strong, CaMeL-like form: every LLM is treated as **untrusted compute**, mediated by context
on input and verification on output.

> A Reasoning Kernel is an architecture in which probabilistic reasoning is treated as an untrusted
> computational resource, mediated by context on input and verification on output.

## The two invariants

- **A — the reasoner never sees raw reality.** Every model invocation gets a context the system
  assembled, controls, and can inspect (`context/`).
- **B — the reasoner never commits reality.** No model output becomes a durable effect except
  through one deterministic verification boundary (`kernel/gate.py`).

The pattern guarantees a **topology, not a property**: it fixes *where* mediation and verification
live, by construction; it does not guarantee any particular policy is safe. Conformance is a
*necessary*, not a *sufficient*, condition.

## Strong form: no trusted reasoner

Following CaMeL (Debenedetti et al., 2025), the kernel contains **no trusted reasoner**. It has two
reasoners at differentiated privilege, *both untrusted* (section references like §5.4 below point to
that paper):

- **P-LLM** (`reasoner/roles.py:PLLM`) — privileged planner; sees only the controlled query + tool
  catalog; emits a typed `Plan`, never prose or code.
- **Q-LLM** (`reasoner/roles.py:QLLM`) — quarantined parser; turns untrusted content into typed
  values; has no tool capability.

The trusted, deterministic kernel is the **interpreter + capability/provenance gate**, never a model.

## Role → module map

| Role (paper)   | Module                          | Reason to change                |
|----------------|---------------------------------|---------------------------------|
| Context        | `context/assembler.py`          | input-assembly / Invariant A    |
| Reasoner(s)    | `reasoner/` (multi-provider)    | a provider or the interface     |
| Conductor      | `kernel/interpreter.py`         | the execution loop              |
| Verifier       | `kernel/gate.py`, `effects.py`  | verification policy             |
| Memory / Trace | `memory/`                       | durability / audit format       |

Reasoner providers: Anthropic, OpenAI, Deepseek (OpenAI-compatible, reusing the `openai` SDK via a
`base_url` — no separate dependency), plus a deterministic `FakeProvider` for key-free tests — all
behind one interface (`reasoner/base.py`). The fungibility corollary is validated live: OpenAI and
Deepseek return schema-valid `Plan`s through the same interface (`just test-live`); Anthropic is
exercised on demand when its key is set.

## No effect bypasses the Verifier — by construction

1. Tool callables live only in `ToolRegistry`, handed only to `EffectDispatcher`; the interpreter
   never holds one.
2. `EffectDispatcher` cannot be constructed without a `Gate`, and `dispatch` checks it
   unconditionally before the callable runs.
3. `ToolCallStep` is the only step kind that invokes a tool callable, and its only handler routes
   through the dispatcher. The other step kinds (`const`, `q_parse`, `subkernel`, `merge`) produce
   values, never external effects.

## Run it

```bash
uv sync --extra dev            # key-free: demo + the full default test suite
just demo        # FakeProvider: legit send commits; injection inert; exfiltration BLOCKED
just test        # key-free suite (with coverage) incl. the conformance + blocking proofs
just lint && just typecheck
just demo-subkernel  # §5.4: delegate untrusted content to an inner kernel at a reduced grant
just demo-limits        # termination: RunLimits aborts the run closed before the second effect
just demo-reasoner-error # fail-closed: a failing reasoner commits nothing (plan_rejected)
just demo-merge      # MergeStep: combine several reads into one value; taint flows through the join

uv sync --all-extras           # adds the provider SDKs for the live flows below
just demo-live   # end-to-end with a REAL planner/parser (needs a key in .env)
just test-live   # optional: real Anthropic/OpenAI/Deepseek round-trips (needs API keys)
```

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the quality bar (coverage gate, strict typing,
pre-commit) and how to configure provider keys. Release notes are in
[`CHANGELOG.md`](CHANGELOG.md); vulnerability reporting and scope in [`SECURITY.md`](SECURITY.md).

## What the kernel enforces

- **Provenance is multi-dimensional**: a `ProvenanceLabel` carries *origin* (`sources`), *where it may
  flow* (`readers`), and *whose data it is* (`subjects`). Third-party data is never auto-released into a
  WRITE — even to the requesting user — and the Q-LLM cannot launder any of these dimensions.
- **Invariant A is typed**: the trusted channel is a `TrustedQuery` (text + label); `const`/inline
  literals DERIVE their label from it, so the trust assumption is explicit rather than by convention.
- **Termination**: `RunLimits` bounds steps / effects / q-parses (and an optional per-call timeout); a
  run exceeding a bound aborts closed (`RunAborted`), committing nothing further. The timeout abort is
  prompt — it does not block waiting on the hung call (`kernel/interpreter.py:_call_reasoner`).
- **Reasoner failure is fail-closed**: a provider that returns no usable output (empty / refused /
  malformed) raises `ReasonerError` (`reasoner/base.py`); the Conductor records it and commits
  nothing, rather than crashing or acting on a partial result. Treating the model as untrusted compute
  means a flaky reasoner can never produce a half-applied effect.
- **Capability composition (§5.4)**: every reasoner is bound to a `CapabilitySet`; the kernel rejects a
  reasoner whose grant exceeds the dispatcher's — a child can never widen authority. A `SubKernelStep`
  delegates untrusted content to an inner kernel at a **clamped, reduced grant**: an injection in that
  content is confined to what the delegated grant permits, even capabilities the outer kernel holds but
  did not delegate (see `just demo-subkernel`). `RunLimits.max_depth` bounds nesting.
- **Static, data-independent control flow**: a `Plan` is a forward-only DAG of five step kinds
  (`const`, `tool`, `q_parse`, `subkernel`, `merge`), executed linearly by `kernel/interpreter.py`; a
  `QuarantineParseStep`'s target schema is fixed at plan time
  (`schema_ref`), never chosen on the quarantined value. No branch, loop, or tool selection is
  conditioned on untrusted content — so control-flow leaks of quarantined data are precluded by
  construction, not by policy (the matching cost is in *Honest limits*).

## Honest limits (fundamental — localized, not dissolved)

- **Conformance ≠ safety**: a pass-through declassifier conforms yet protects nothing. The pattern
  guarantees a topology; the *policy* carries correctness.
- **Verification determinism is a discipline, not a typed invariant**: the commit path has no
  LLM-as-judge (§6.2) and the Q-LLM is untrusted — but `DeclassPolicy` is a `Protocol` the Gate calls
  blindly; nothing in the types forbids an implementation from consulting a model. Determinism is
  *required of* the declassifier, not *enforced on* it.
- **The trust boundary is axiomatic**: the kernel's guarantees are conditional on configuration it does
  not attest. A `TrustedQuery`'s trusted label is *assumed*, not verified; the capability grant, tool
  catalog, Q-LLM schemas, and `DeclassPolicy` are host-supplied. Conformance protects nothing if that
  boundary is drawn wrong — the kernel fixes the topology, the host owns the inputs.
- **The declassifier is the residual risk surface**: every `may_declassify=True` is a deliberate, traced
  trust decision.
- **No data-dependent control flow (a deliberate trade)**: because the plan is a static DAG (see *What
  the kernel enforces*), it cannot branch or loop on parsed content — the price of precluding
  control-flow leaks. An "if the email says X, do Y" must be lifted into a typed value the Gate can
  inspect, not a runtime branch on quarantined text.
- **No atomicity / rollback**: an effect already committed is real even if a later step (or the outer run
  of a sub-kernel) fails — same semantics as a flat plan. The shared trace makes the partial commit
  visible; the kernel does not pretend to offer transactions.
- **Object-level taint (deferred, not a hole)**: a label covers a whole value. The value-COMBINING step
  (`MergeStep`) labels its result with the *join* of its inputs, so a composite of differing provenances
  carries one label that over-approximates them all — strictly safer than per-field labels. Field-level
  labels (recovering a trusted field out of a mixed structure without over-tainting it) stay deferred:
  they buy precision, not soundness, and only pay off once a real use case needs them.
