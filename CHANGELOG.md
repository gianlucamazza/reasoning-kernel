# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-05-31

### Changed

- **PyPI distribution name** is now `capability-reasoning-kernel` (the import stays `reasoning_kernel`,
  and the repository stays `reasoning-kernel`): `reasoning-kernel` is taken on PyPI by an unrelated
  project. Released on real PyPI in addition to TestPyPI.

## [0.4.0] - 2026-05-31

A minor release: a discoverable public API at the package root, with an "Embedding the kernel" snippet,
a maturity note, and a license section in the README. No breaking changes.

### Added

- **Public top-level API**: `reasoning_kernel` now re-exports the key building blocks and contracts
  (`Interpreter`, `Gate`, `EffectDispatcher`, `PLLM`/`QLLM`, `ToolRegistry`, `ToolSpec`, `RunContext`,
  `RunLimits`, the Plan IR, provenance types, …) under `__all__`, so integrators import from the
  package root. See the README's *Embedding the kernel* section.

## [0.3.0] - 2026-05-31

A feature release: the value-combining `MergeStep` closes the last deferred item, with sound
object-level taint and no change to the trusted core. No breaking API changes.

### Added

- **`MergeStep`** — the value-COMBINING step. It folds several earlier results into one structured
  value, labelled with the *join* of its inputs (sources union + `DERIVED`, readers intersection,
  subjects union), so taint only ever increases. This lets a single-`source` Q-LLM parse or sub-kernel
  work over a composite of several reads. Taint stays object-level (the join over-approximates, which
  is strictly safer); field-level labels remain deferred. (`just demo-merge`)

## [0.2.0] - 2026-05-31

A hardening release: the kernel now fails closed on every unsafe path, the trusted core is type-checked
in strict mode with no suppressions, provider models are current, and composition is real. No breaking
API changes.

### Added

- **Composable nested sub-kernels (§5.4)**: a `SubKernelStep` delegates untrusted content to an inner
  kernel at a **clamped, reduced grant** — an injection in that content is confined to what the
  delegated grant permits. `RunLimits.max_depth` bounds nesting. (`just demo-subkernel`)
- **Multi-dimensional provenance**: a `ProvenanceLabel` carries *origin* (`sources`), *flow*
  (`readers`), and *data subject* (`subjects`). Third-party data is never auto-released into a WRITE,
  and the Q-LLM cannot launder any dimension.
- **Termination bounds**: `RunLimits` caps steps / effects / q-parses, plus an optional per-call
  reasoner timeout; a run exceeding a bound aborts closed (`RunAborted`).
- **Quality bar**: coverage gate at 85% (`pytest-cov`), `pyright` strict over `schemas` + `kernel` +
  `memory`, pre-commit hooks, and GitHub Actions CI (uv + just) running lint / typecheck / covered
  tests on push & PR, with an optional manual live-provider job.
- **Plan IR robustness**: `ArgRef.path` is validated at plan-construction time — a malformed dotted
  path (empty / leading / trailing / doubled `.`) is rejected with a clear error instead of surfacing
  opaquely at navigation time.
- **Docs**: `docs/DEVELOPMENT.md` (setup, quality bar, provider configuration), a typed-library
  `py.typed` marker, and a complete *Honest limits* section in the README — the trust boundary is
  axiomatic, control flow is static and data-independent, and verification determinism is a discipline
  rather than a typed invariant (mirrored in `DEVELOPMENT.md` rule #2 and the `DeclassPolicy` docstring).
- **Robustness tests**: provider-failure fail-closed, prompt timeout abort, the demo tools failing
  closed on malformed world state, and key-free coverage of the registry, value store, capability
  algebra, and the demo declassifier's rejection branches.

### Changed

- **Provider models refreshed to 2026**: Anthropic `claude-sonnet-4-6` (variant `claude-opus-4-8`),
  OpenAI `gpt-5.5` (variant `gpt-5.5-pro`), Deepseek `deepseek-v4-flash` (variant `deepseek-v4-pro`).
  Deepseek is OpenAI-compatible and reuses the `openai` SDK via `base_url` (no separate dependency).
- **Trusted core kept free of `Any`**: `TaintedValue.value` and the `ValueStore` path-navigation are
  typed `object`; `_eval_step` is exhaustive over the `PlanStep` union (a new step kind that is not
  handled is a type error).
- **No suppressions**: removed every `# noqa` / `# type: ignore` from `src` and `tests`, fixing the
  root cause instead (e.g. tests construct `RunId` / `StepId` via their constructors).

### Fixed

- **Reasoner failure is fail-closed**: a provider returning no usable output (empty / refused /
  malformed) raises `ReasonerError`; the Conductor records it and commits nothing instead of crashing
  or acting on a partial result.
- **Prompt-timeout abort is prompt**: the timeout no longer blocks on the hung call — the executor is
  shut down without waiting rather than used as a context manager.
- **Demo tools fail closed**: `read_inbox` on an empty inbox raises a semantic `ValueError` rather than
  an opaque `IndexError`.
- Closed a provenance gate footgun and made the Conductor fail closed on any plan it cannot safely run.

## [0.1.0] - 2026

Initial reference implementation of the Reasoning Kernel pattern (strong / CaMeL-like form): the two
invariants, no-effect-bypasses-the-Verifier by construction, the deterministic declassification seam,
and the worked email-exfiltration demo.

[0.4.1]: https://github.com/gianlucamazza/reasoning-kernel/releases/tag/v0.4.1
[0.4.0]: https://github.com/gianlucamazza/reasoning-kernel/releases/tag/v0.4.0
[0.3.0]: https://github.com/gianlucamazza/reasoning-kernel/releases/tag/v0.3.0
[0.2.0]: https://github.com/gianlucamazza/reasoning-kernel/releases/tag/v0.2.0
[0.1.0]: https://github.com/gianlucamazza/reasoning-kernel/releases/tag/v0.1.0
