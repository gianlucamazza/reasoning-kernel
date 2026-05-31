# Security Policy

## Scope — read this first

`reasoning-kernel` is a **reference implementation of an architecture pattern**, not a turn-key
security product. It demonstrates how to make prompt injection *structurally* unable to cause an
unauthorized effect: the LLM is treated as untrusted compute, and every real-world effect passes a
deterministic Gate. What the pattern guarantees is a **topology**; the *policy* you plug in carries
correctness.

In particular (see the "Honest limits" section of the [README](README.md)):

- A pass-through declassifier conforms to the pattern yet protects nothing — **the declassifier is the
  residual risk surface**. Every `may_declassify=True` is a deliberate, traced trust decision.
- There is no atomicity / rollback: an effect already committed is real even if a later step fails.

So a "vulnerability" here means a way to make the **kernel itself** commit an effect that its Gate and
labels should have blocked — i.e. a hole in the mechanism (`kernel/`, `schemas/`, `memory/`), not a
permissive policy written on top of it.

## Threat model

- **The attacker controls untrusted data** — email bodies, tool outputs, anything a READ tool returns —
  and can put arbitrary instructions in it.
- **The attacker does NOT control host-supplied configuration**: the `TrustedQuery` and its label, the
  capability grants, the tool catalog, the Q-LLM schemas, and the `DeclassPolicy`. These are trusted by
  assumption (see *the trust boundary is axiomatic* in the README's *Honest limits*).
- **Trusted computing base**: the deterministic interpreter + gate (`kernel/`), the schemas
  (`schemas/`), and the value store / trace (`memory/`). No LLM is in the TCB.
- **Out of scope**: supply-chain compromise, side channels, denial of service beyond `RunLimits`, and a
  compromised host. The reasoner is assumed possibly-malicious; the host config is assumed correct.

## Supported versions

| Version | Supported |
|---------|-----------|
| `0.4.x` | ✅ |
| `< 0.4` | ❌ |

## Reporting a vulnerability

Please report privately — do **not** open a public issue for a suspected vulnerability.

- Preferred: open a [GitHub private security advisory](https://github.com/gianlucamazza/reasoning-kernel/security/advisories/new).
- Or email **homen3@gmail.com**.

Include a minimal reproduction (a plan + tool/policy setup that commits an effect that should have been
blocked), the expected vs. actual behavior, and the affected version/commit. Expect an initial
acknowledgement within a few days. As a single-maintainer reference project there is no formal SLA, but
mechanism-level issues are taken seriously and will be addressed in a `0.4.x` patch.
