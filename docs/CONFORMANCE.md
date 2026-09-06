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
