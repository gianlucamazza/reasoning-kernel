# Development

How to work on the kernel, the quality bar it enforces, and how to run the live flows.

## Setup

```bash
uv sync --extra dev       # key-free suite, including SDKs for mocked provider contract tests
uv sync --all-extras      # development plus explicit provider extra
uv sync --all-extras --locked  # reproduce CI without changing dependency resolution
```

Python 3.12+ is required. The default suite needs no API keys: it runs against the deterministic
`FakeProvider`.

## Common tasks (justfile)

| Command            | What it does                                                              |
|--------------------|--------------------------------------------------------------------------|
| `just check`       | `lint` + `typecheck` + `test` + `docs-check` + `package-check` (current Python)        |
| `just release-check` | Offline aggregate plus the online dependency security gate |
| `just audit-deps` | Audit every locked extra/platform against known vulnerabilities |
| `just demo`        | Worked demo (FakeProvider): legit send commits; injection inert; exfil blocked |
| `just conformance` | Complete key-free `operational-v1` reference profile                    |
| `just docs-check`  | Local links, anchors, release metadata and claim-drift guard             |
| `just demo-subkernel` | §5.4 composition demo: untrusted content delegated at a reduced grant  |
| `just demo-limits` | Termination demo: `RunLimits` aborts the run closed before the second effect |
| `just demo-reasoner-error` | Fail-closed demo: a failing reasoner commits nothing (`plan_rejected`) |
| `just demo-merge`  | `MergeStep` demo: combine several reads into one value; taint flows through the join |
| `just test`        | Default suite **with coverage** (live tests excluded)                     |
| `just lint`        | `ruff check` + `ruff format --check`                                      |
| `just fix`         | `ruff check --fix` + `ruff format`                                        |
| `just typecheck`   | `pyright`                                                                 |
| `just demo-live`   | End-to-end with a **real** planner/parser (needs a key in `.env`)        |
| `just test-live`   | Real Anthropic/OpenAI/DeepSeek round-trips (needs API keys)              |

## Quality bar

- **Coverage gate**: `just test` runs under `pytest-cov` and fails below **85%**
  (`[tool.coverage.report] fail_under` in `pyproject.toml`). The `demo/` package is excluded from the
  measure — it is runnable examples, exercised by `just demo*`, not by the unit suite.
- **Strict typing on the security-critical layers**: `pyright` runs in `strict` mode over
  `src/reasoning_kernel/schemas` (the contract layer), `src/reasoning_kernel/kernel` (the trusted
  core: interpreter, gate, dispatcher, taint), and `src/reasoning_kernel/memory` (the `ValueStore`
  that holds tainted values and the append-only `TraceWriter`). Provider integrations stay at
  `basic`. The trusted core is kept free of `Any` leakage — e.g. `TaintedValue.value` and the
  `ValueStore` path-navigation are typed `object`, since the kernel never inspects the payload.
- **No suppressions as a shortcut**: prefer fixing the root cause over `# noqa` / `# type: ignore`.
- **pre-commit**: hooks run ruff (+ format), the standard hygiene checks, and `pyright` strict on
  `schemas` + `kernel` + `memory`. Install once with `uv run pre-commit install`.

CI (`.github/workflows/ci.yml`) runs `just check` on a Python 3.12 + 3.13 + 3.14 matrix on push / PR
and on release tags, plus a separate documentation check and artifact upload/download checksum round
trip. Locally, `just check` covers the current Python only; it does not claim matrix or live-provider
qualification. `just release-check` adds the same online dependency audit required by CI and
release publication. It exports `uv.lock` to a temporary standard pylock file and uses pinned
pip-audit without installing dependencies, ignoring advisories or applying automatic fixes.
`just package-check` validates wheel/sdist metadata and an isolated wheel install. The live job runs
manually and when a release calls the reusable workflow with required providers. The release
workflow now requires both DeepSeek and OpenAI before package build or publication. Release notes live in
[`CHANGELOG.md`](../CHANGELOG.md);
security reporting and scope in [`SECURITY.md`](../SECURITY.md).

The conformance CLI is included in wheel smoke testing. It imports a trusted host factory, executes
the selected fixed profile and returns a non-zero status for failures, inconclusive evidence or invalid suite
configuration; it never calls a live provider on its own.

The pyright configuration selects `.venv` explicitly, avoiding accidental system-Python imports.
Operational contracts and migration are in [OPERATIONS.md](OPERATIONS.md); the integration
acceptance checklist is in [CONFORMANCE.md](CONFORMANCE.md). The capability-mediated topology
and threat model are described in the [working paper](whitepaper/reasoning-kernel-whitepaper.md)
(PDF snapshot alongside; Zenodo deposit on hold, no DOI). Provider refusal/truncation handling
follows the [official structured-output contract](https://developers.openai.com/api/docs/guides/structured-outputs)
and is exercised with SDK-shaped fixtures without API calls.

## Provider configuration

Configuration is centralized in `src/reasoning_kernel/config.py` (`settings`, an SSOT loaded from
env / `.env`). Copy the template and fill in the keys you need:

```bash
cp .env.example .env
```

Keys are accepted under either their conventional bare name or an `RK_`-prefixed alias:

| Provider | Env var | Default model (higher-capability option) |
|----------|---------|-----------------------------------------|
| Anthropic | `ANTHROPIC_API_KEY` / `RK_ANTHROPIC_API_KEY` | `claude-sonnet-5-5` (`claude-opus-5-5`) |
| OpenAI | `OPENAI_API_KEY` / `RK_OPENAI_API_KEY` | `gpt-6.1-sol` (`gpt-6-astra`) |
| DeepSeek | `DEEPSEEK_API_KEY` / `RK_DEEPSEEK_API_KEY` | `deepseek-flash` (`deepseek-v4-pro`) |

Other overrides (defaults in `config.py`): `RK_LLM_PROVIDER_DEFAULT`, `RK_LLM_MODEL_*`,
`RK_DEEPSEEK_BASE_URL`, `RK_LLM_TIMEOUT_SECONDS`, `RK_LLM_MAX_TOKENS`. With no selector, live tests
skip providers whose keys are absent. Set `RK_LIVE_PROVIDERS` to a comma-separated set to exclude
all other providers and require a configured key for every selected provider:

```bash
RK_LIVE_PROVIDERS=deepseek,openai just test-live
```

Model IDs were checked against the official catalogs on 2026-10-04:
[OpenAI](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[Anthropic](https://platform.claude.com/docs/en/models/overview), and
[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing). The defaults preserve the balanced
or efficient tier. Model overrides remain explicit; the kernel never switches models after a failure.
DeepSeek's `deepseek-flash` selects V4.1 Flash; the retired `deepseek-v4-flash` name is a provider-side
compatibility alias and is no longer used by the kernel's defaults or live qualification cases.

OpenAI GPT-6.1 Sol supports Chat Completions without tool calling. This matches the kernel's
structured-output contract: the model emits data, and the kernel dispatches tools through its Gate.
The adapter uses native JSON Schema output and falls back to locally validated JSON only when the
API explicitly rejects `response_format`. DeepSeek uses the same locally validated JSON mode.
The adapters omit reasoning-effort overrides, so provider defaults apply; output token limits also
cover reasoning tokens. OpenAI and Anthropic higher-capability options need separate live qualification.

`.env` is gitignored — never commit real keys.

## Where things live

See the role → module map in the [README](../README.md). The two rules to keep in mind when
changing code:

1. **No effect bypasses the Verifier.** Tool callables live only in `ToolRegistry`, handed only to
   `EffectDispatcher`, which cannot be built without a `Gate` and checks it before every call. Do not
   give the interpreter a path to a callable.
2. **The commit path stays deterministic.** No LLM-as-judge on verification (§6.2). Anything that
   relaxes taint must go through the single, auditable `DeclassPolicy` seam — and that seam is
   *required* to be deterministic, a discipline the `Protocol` documents but the type system does not
   enforce.

## OpenAI qualification

The 0.6.3 candidate passed six live checks on 2026-10-04 using the current defaults: OpenAI
`gpt-6.1-sol` (Plan plus operational Q-LLM) and DeepSeek `deepseek-flash` (Plan plus operational
Q-LLM), with explicit Plan cases for `deepseek-flash` and `deepseek-v4-pro`. The SDK was
OpenAI 3.19.2. Anthropic was excluded because no key was configured; none of the selected providers
was skipped. These are contract checks with synthetic data and in-memory effects, not a quality or
performance benchmark. GPT-6 Astra and Claude Opus 5.5 have not been live-qualified.

The published 0.6.2 wheel passed the existing live Plan and operational Q-LLM tests on 2026-10-04
using the configured `gpt-5.5` model and OpenAI SDK 3.19.2. Tests imported the public wheel in an
isolated environment, with synthetic inputs and in-memory tool effects. This post-release evidence
is attached separately to the GitHub Release; the original tag and distributions are unchanged.
This historical qualification does not cover the updated 0.6.3 defaults or Anthropic.

Subsequent releases require `RK_LIVE_PROVIDERS=deepseek,openai` and explicitly pass both API secrets.
Unavailable keys, credits, model access or provider responses fail the gate before publication.
Successful live CI runs retain `live-qualification` artifacts (JUnit and version/model metadata)
for 90 days. Failure logs are not uploaded as qualification artifacts. The metadata records the
requested default models; parametrized DeepSeek model cases are identified in JUnit.
