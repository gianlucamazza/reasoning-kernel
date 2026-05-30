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
reasoners at differentiated privilege, *both untrusted*:

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

Reasoner providers: Anthropic, OpenAI, Deepseek (OpenAI-compatible), plus a deterministic
`FakeProvider` for key-free tests — all behind one interface (`reasoner/base.py`).

## No effect bypasses the Verifier — by construction

1. Tool callables live only in `ToolRegistry`, handed only to `EffectDispatcher`; the interpreter
   never holds one.
2. `EffectDispatcher` cannot be constructed without a `Gate`, and `dispatch` checks it
   unconditionally before the callable runs.
3. `ToolCallStep` is the only effectful step kind, and its only handler routes through the dispatcher.

## Run it

```bash
uv sync --extra dev
just demo        # legit send commits; injection inert; exfiltration BLOCKED
just test        # key-free suite incl. the conformance + blocking proofs
just lint && just typecheck
just test-live   # optional: real Anthropic/OpenAI/Deepseek (needs API keys)
```

## Honest limits

- **Conformance ≠ safety**: a pass-through declassifier conforms yet protects nothing.
- **Verification stays deterministic**: no LLM-as-judge on the commit path (§6.2).
- **Provenance is effectiveness, not conformance**: a run without taint tracking still conforms.
