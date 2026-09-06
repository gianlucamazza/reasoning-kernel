set dotenv-load := true

# everything CI runs, locally, in one command
check: lint typecheck test

# Build and validate the distribution, including an install outside the checkout.
package-check:
    uv build --clear
    uv run twine check --strict dist/*
    uv run python scripts/check_artifacts.py dist

# lint (ruff check + format check)
lint:
    uv run ruff check src/ tests/ scripts/
    uv run ruff format --check src/ tests/ scripts/

# auto-fix lint issues
fix:
    uv run ruff check --fix src/ tests/ scripts/
    uv run ruff format src/ tests/ scripts/

# type check (strict on schemas/ + kernel/, basic elsewhere — see pyproject)
typecheck:
    uv run pyright

# run tests with coverage (live tests excluded by default via addopts -m 'not live')
test *args:
    uv run pytest --cov --cov-report=term-missing {{ args }}

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

# run the termination demo (RunLimits aborts a run closed before it exceeds a bound)
demo-limits:
    uv run python -m reasoning_kernel.demo.run_limits

# run the fail-closed demo (a failing reasoner commits nothing — plan_rejected, no effect)
demo-reasoner-error:
    uv run python -m reasoning_kernel.demo.reasoner_error

# run the merge demo (combine several reads into one value; taint flows through the join)
demo-merge:
    uv run python -m reasoning_kernel.demo.merge
