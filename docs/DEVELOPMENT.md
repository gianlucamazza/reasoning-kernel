# Development

How to work on the kernel, the quality bar it enforces, and how to run the live flows.

## Setup

```bash
uv sync --extra dev       # key-free: demo + the full default test suite
uv sync --all-extras      # also installs the provider SDKs (anthropic, openai) for live flows
```

Python 3.12+ is required. The default suite needs no API keys: it runs against the deterministic
`FakeProvider`.

## Common tasks (justfile)

| Command            | What it does                                                              |
|--------------------|--------------------------------------------------------------------------|
| `just demo`        | Worked demo (FakeProvider): legit send commits; injection inert; exfil blocked |
| `just demo-subkernel` | §5.4 composition demo: untrusted content delegated at a reduced grant  |
| `just test`        | Default suite **with coverage** (live tests excluded)                     |
| `just lint`        | `ruff check` + `ruff format --check`                                      |
| `just fix`         | `ruff check --fix` + `ruff format`                                        |
| `just typecheck`   | `pyright`                                                                 |
| `just demo-live`   | End-to-end with a **real** planner/parser (needs a key in `.env`)        |
| `just test-live`   | Real Anthropic/OpenAI/Deepseek round-trips (needs API keys)              |

## Quality bar

- **Coverage gate**: `just test` runs under `pytest-cov` and fails below **85%**
  (`[tool.coverage.report] fail_under` in `pyproject.toml`). The `demo/` package is excluded from the
  measure — it is runnable examples, exercised by `just demo*`, not by the unit suite.
- **Strict typing on the security-critical layers**: `pyright` runs in `strict` mode over
  `src/reasoning_kernel/schemas` (the contract layer) and `src/reasoning_kernel/kernel` (the trusted
  core: interpreter, gate, dispatcher, taint). Provider integrations stay at `basic`. The trusted
  core is kept free of `Any` leakage — e.g. `TaintedValue.value` is typed `object`, since the kernel
  never inspects the payload.
- **No suppressions as a shortcut**: prefer fixing the root cause over `# noqa` / `# type: ignore`.
- **pre-commit**: hooks run ruff (+ format), the standard hygiene checks, and `pyright` strict on
  `schemas` + `kernel`. Install once with `uv run pre-commit install`.

CI (`.github/workflows/ci.yml`) runs lint, typecheck, and the covered test suite on push / PR. The
live provider job is manual only (`workflow_dispatch`), reading keys from repository secrets.

## Provider configuration

Configuration is centralized in `src/reasoning_kernel/config.py` (`settings`, an SSOT loaded from
env / `.env`). Copy the template and fill in the keys you need:

```bash
cp .env.example .env
```

Keys are accepted under either their conventional bare name or an `RK_`-prefixed alias:

| Provider  | Env var                                  | Default model (more capable variant)        |
|-----------|------------------------------------------|---------------------------------------------|
| Anthropic | `ANTHROPIC_API_KEY` / `RK_ANTHROPIC_API_KEY` | `claude-sonnet-4-6` (`claude-opus-4-8`) |
| OpenAI    | `OPENAI_API_KEY` / `RK_OPENAI_API_KEY`       | `gpt-5.5` (`gpt-5.5-pro`)               |
| Deepseek  | `DEEPSEEK_API_KEY` / `RK_DEEPSEEK_API_KEY`   | `deepseek-v4-flash` (`deepseek-v4-pro`) |

Other overrides (defaults in `config.py`): `RK_LLM_PROVIDER_DEFAULT`, `RK_LLM_MODEL_*`,
`RK_DEEPSEEK_BASE_URL`, `RK_LLM_TIMEOUT_SECONDS`. A live test or demo **skips** any provider whose
key is absent, so partial configuration is fine.

Each provider has a sensible default and a more capable variant (the parenthesised id above). Model
ids are current as of May 2026; the defaults are the cost-effective tier, the variants the
frontier tier. For Deepseek the legacy `deepseek-chat` / `deepseek-reasoner` names still resolve as
deprecated aliases of `deepseek-v4-flash` but should not be used.

`.env` is gitignored — never commit real keys.

## Where things live

See the role → module map in the [README](../README.md). The two rules to keep in mind when
changing code:

1. **No effect bypasses the Verifier.** Tool callables live only in `ToolRegistry`, handed only to
   `EffectDispatcher`, which cannot be built without a `Gate` and checks it before every call. Do not
   give the interpreter a path to a callable.
2. **The commit path stays deterministic.** No LLM-as-judge on verification (§6.2). Anything that
   relaxes taint must go through the single, auditable `DeclassPolicy` seam.
