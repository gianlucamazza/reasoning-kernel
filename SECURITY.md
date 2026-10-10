# Security Policy

## Scope — read this first

`reasoning-kernel` is a **reference implementation of an architecture pattern**, not a turn-key
security product. CaMeL-style control/data-flow separation **reduces** the injection-to-effect
risk when the assumptions in the README hold: the LLM is treated as untrusted compute, and every
*registered* real-world effect passes a Gate. The pattern fixes a **topology**; the *policy* you
plug in defines authority and carries correctness. It does not prove that prompt injection is
unable to cause an unauthorized effect.

In particular (see [Threat model & limits](README.md#threat-model--limits) in the README):

- A pass-through declassifier conforms to the pattern yet protects nothing — **the declassifier is the
  residual risk surface**. Every `may_declassify=True` is a deliberate, traced trust decision.
- There is no atomicity / rollback: an effect already committed is real even if a later step fails.
- Operational sessions require explicit egress declarations and record uncertain effects; audit
  storage failures halt work but cannot undo an external call. See [operations](docs/OPERATIONS.md).
- Providers are data recipients authorized by the host. Quarantine does not enforce confidentiality
  against the selected provider. SQLite audit is not tamper-proof or a substitute for host access control.

So a "vulnerability" here means a way to make the **kernel itself** commit an effect that its Gate and
labels should have blocked — i.e. a hole in the mechanism (`kernel/`, `schemas/`, `memory/`), not a
permissive policy written on top of it.

## Threat model

- **The attacker controls untrusted data** — email bodies, tool outputs, anything a READ tool returns —
  and can put arbitrary instructions in it.
- **The attacker does NOT control host-supplied configuration**: the `TrustedQuery` and its label, the
  capability grants, the tool catalog, the Q-LLM schemas, and the `DeclassPolicy`. These are trusted by
  assumption (see *Assumptions* in the README's *Threat model & limits*).
- **Trusted computing base**: the deterministic interpreter + gate (`kernel/`), the schemas
  (`schemas/`), and the value store / trace (`memory/`). No LLM is in the TCB.
- **Out of scope / non-goals**: supply-chain compromise, side channels, denial of service beyond
  `RunLimits`, a compromised host, policy bugs, a planner that only uses *allowed* tools (including
  data exfiltration via those tools), and formal impossibility proofs. The reasoner is assumed
  possibly-malicious; the host config is assumed correct.

## Supported versions

| Version | Supported |
|---------|-----------|
| `0.6.x` | ✅; validate host adapters before application use |
| `0.6.0rc1` | Superseded candidate; upgrade to `0.6.4` |
| `0.5.x` | ✅; validate host adapters before application use |
| `0.4.x` | ✅ |
| `0.5.0rc1`, `0.5.0rc2` | Superseded candidates; upgrade to `0.5.0` |
| `< 0.4` | ❌ |

## Reporting a vulnerability

Please report privately — do **not** open a public issue for a suspected vulnerability.

- Preferred: open a [GitHub private security advisory](https://github.com/gianlucamazza/reasoning-kernel/security/advisories/new).
- Or email **info@gianlucamazza.it**.

Include a minimal reproduction (a plan + tool/policy setup that commits an effect that should have been
blocked), the expected vs. actual behavior, and the affected version/commit. Expect an initial
acknowledgement within a few days. As a single-maintainer reference project there is no formal SLA, but
mechanism-level issues are taken seriously and addressed in the applicable supported release line.
