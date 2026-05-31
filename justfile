set dotenv-load := true

# lint (ruff check + format check)
lint:
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/

# auto-fix lint issues
fix:
    uv run ruff check --fix src/ tests/
    uv run ruff format src/ tests/

# type check (strict on schemas/, basic elsewhere — see pyproject)
typecheck:
    uv run pyright

# run tests (live tests excluded by default via addopts -m 'not live')
test *args:
    uv run pytest {{ args }}

# run the live tests that hit real provider APIs (needs API keys)
test-live:
    uv run pytest -m live

# run the worked demo with the deterministic FakeProvider (no keys needed)
demo:
    uv run python -m reasoning_kernel.demo.email_exfil

# run the demo end-to-end against a REAL provider (needs a key in .env)
demo-live:
    uv run python -m reasoning_kernel.demo.live_run

# run the composable sub-kernel demo (delegate untrusted content under a reduced grant)
demo-subkernel:
    uv run python -m reasoning_kernel.demo.subkernel
