# Conformance and operational acceptance

Conformance establishes mediation points. Policy correctness and host configuration are separate
requirements; an allow-all policy can conform without useful confidentiality protection.

| Requirement | Test evidence |
|---|---|
| Every model input is assembled by the host/kernel | `test_invariant_a`, `test_subject_provenance` |
| Each callable invocation has its own preceding Gate authorization | `test_no_bypass_conformance`, `test_operational` |
| Parsing, merging and delegation cannot launder provenance | `test_provenance_propagation`, `test_merge`, `test_subkernel` |
| Delegated authority never exceeds its parent | `test_composition`, `test_subkernel`, `test_operational` |
| Egress READs receive provenance checks | `test_operational` |
| Normalized checked values are the executed values | `test_operational` |
| Contexts/budgets are isolated between roots and shared within a tree | `test_operational` |
| Failure stops later work and preserves partial-effect evidence | `test_operational`, `test_reasoner_robustness` |
| Storage failure before start prevents the callable | `test_operational` |
| Process crashes leave durable evidence; reopening cannot replay | `test_operational` |
| Provider refusal, truncation and fallback errors are terminal | `test_provider_contracts` |

Reproduce these scenarios against application policies and wiring, including tools returning invalid
output or raising after an effect. Validators and policies are trusted code and must not perform I/O.
Supplying an external model authorizes data transfer; quarantining it does not make that transfer private.

Before application use, verify identity mapping, destination restrictions, adapter provenance, egress
declarations, finite adapter timeouts, shared-client thread safety, audit access/retention and operator
reconciliation. Exercise clean and injected input with the chosen providers. Record local, CI,
published-artifact and live-adapter evidence separately.

Conformance does not include rollback, exactly-once external effects, automatic recovery, tamper-proof
storage, a Python security sandbox or correctness of arbitrary declassification policies.

## Executable profiles

The `reasoning_kernel.conformance` package turns the requirements above into fixed host acceptance
profiles. Use `gate-v1` when the host embeds the verifier as a pre-pipeline checkpoint but does not
use `RunSession`; use `operational-v1` for the complete operational runtime. A suite selects one
profile and must provide each of its `ScenarioKind` values exactly once.

### `gate-v1`

| Scenario | Required evidence |
|---|---|
| `gate_authorized` | An authorized proposal is allowed, not enforcement-skipped, and audited |
| `gate_capability_denied` | Missing capability is denied, enforcement-skipped, audited, and launches nothing |
| `gate_tainted_egress_denied` | Tainted egress is denied, enforcement-skipped, audited, and launches nothing |
| `gate_internal_error_denied` | An internal mapping error fails closed, is audited, and launches nothing |

### `operational-v1`

| Scenario | Required evidence |
|---|---|
| `benign_effect` | An authorized effect succeeds and is externally observable |
| `injected_control` | The run succeeds, an authorized effect is observed, and the trusted observer reports no unauthorized effect |
| `injected_egress` | An attempted tainted exfiltration is blocked with no unauthorized effect |
| `capability_denied` | Missing authority blocks the WRITE before its callable |
| `invalid_output` | Invalid adapter output is recorded and later effects do not run |
| `tool_failure_before_effect` | The outcome is uncertain, no effect is observed and execution stops |
| `tool_failure_after_effect` | The effect is observed but remains uncertain and execution stops |
| `audit_failure_before_dispatch` | Failure to persist the start prevents the callable |
| `crash_reopen_no_replay` | The incomplete root is discoverable and its ID cannot be reused |

The host factory is trusted Python code and must return a `ConformanceSuite`. Operational scenario
callables build fresh `RunSession` instances and test worlds. Gate scenarios exercise the host's real
checkpoint in enforcement mode. Both return `ConformanceObservation`. `authorized_effects`,
`unauthorized_effects` and `subsequent_effects` count externally visible WRITE effects, not READ calls
or trace records. The host must observe the destination system or a faithful test double; the kernel
cannot infer an external commit from its own log.
The suite name is a 1–64 character identifier containing only letters, digits, `.`, `_` or `-`; it
must not contain a customer name, path or other operational data.

The report proves only the fixed checks over the observations supplied by the host. In particular,
`injected_control` relies on the trusted observer to classify destination-system effects correctly;
the runner does not independently discover or authenticate those effects. A host that misclassifies
an unauthorized destination as authorized can produce misleading evidence. Preserve observer code in
review and test it against a faithful destination double or the controlled live system.

```python
from reasoning_kernel.conformance import ConformanceScenario, ConformanceSuite, ScenarioKind

def build_suite() -> ConformanceSuite:
    return ConformanceSuite(
        name="my-agent",
        profile="operational-v1",
        scenarios=(
            ConformanceScenario(ScenarioKind.BENIGN_EFFECT, run_benign),
            # ...exactly one callable for every operational-v1 ScenarioKind...
        ),
    )
```

Run `reasoning-kernel-conformance my_agent.conformance:build_suite --output conformance.json`.
The JSON schema is versioned independently from the profile. A report is deliberately payload-free
and is evidence from trusted host observers, not a signed attestation. Passing it does not establish
production identity mapping, credentials, network policy, retention or live-adapter correctness.

In CI, install an exact package version, run the command above and retain `conformance.json` as an
artifact only after the command exits successfully. Inspect `cases[].outcome` and `cases[].checks`:
`fail` means observed evidence violated a fixed expectation, while `inconclusive` means the scenario
could not produce trustworthy evidence. Neither is a pass and there is no permissive CLI override.
