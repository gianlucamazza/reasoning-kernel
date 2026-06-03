# CLAUDE.md — reasoning-kernel

Framework-agnostic Python **reference implementation** of the Reasoning Kernel pattern (strong,
CaMeL-like form; Debenedetti et al. 2025): the LLM is treated as untrusted compute, mediated by
context on input and verification on output. Published to PyPI as `capability-reasoning-kernel`.
Remote: `gianlucamazza/reasoning-kernel`.

## The two invariants (do not violate)
- **A** — the reasoner never sees raw reality: every model call gets a system-assembled, inspectable
  context (`src/reasoning_kernel/context/`).
- **B** — the reasoner never commits reality: no model output becomes a durable effect except through
  the single deterministic gate (`src/reasoning_kernel/kernel/gate.py`).

The pattern fixes a *topology*, not a policy guarantee — keep mediation/verification at those
boundaries by construction.

## Stack & layout
- Python, `uv` (uv.lock), `pyproject.toml`, `just`. Lint Ruff, types pyright.
- `src/reasoning_kernel/`: `context/` · `kernel/` (gate) · `reasoner/` · `memory/` · `schemas/` · `demo/`

## Commands
```bash
just lint        # ruff
just fix         # ruff --fix
just typecheck   # pyright
just test-live   # tests against live model
just demo        # run demo (also: demo-live, demo-subkernel, demo-limits, demo-merge, demo-reasoner-error)
uv sync          # install/refresh env
```

## Conventions
- It's a reference impl + spec, not a turn-key product — favor clarity and conformance over features.
- Changes touching invariants A/B must preserve the topology; update `docs/` and the README spec.
