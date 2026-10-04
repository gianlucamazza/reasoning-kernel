set dotenv-load := true

# Complete offline quality gate for the current Python; CI adds the matrix and artifact round trip.
check: lint typecheck test docs-check package-check

# Full current-Python release gate, including the online vulnerability database.
release-check: check audit-deps

# Audit every locked extra/platform through the standard pylock format; never install or fix.
audit-deps:
    #!/usr/bin/env bash
    set -euo pipefail
    audit_dir=$(mktemp -d)
    trap 'rm -rf "$audit_dir"' EXIT
    uv export --all-extras --locked --no-emit-project --format pylock.toml --output-file "$audit_dir/pylock.toml" --quiet
    uvx --from pip-audit==2.10.1 pip-audit --locked --strict --progress-spinner off "$audit_dir"

# Build and validate the distribution, including an install outside the checkout.
package-check:
    uv build --clear
    uv run twine check --strict dist/*
    uv run python scripts/check_artifacts.py dist

# validate documentation structure, claims and release metadata
docs-check:
    uv run python scripts/check_docs.py

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
test-live *args:
    uv run pytest -m live {{ args }}

# run the worked demo with the deterministic FakeProvider (no keys needed)
demo:
    uv run python -m reasoning_kernel.demo.email_exfil

# run the complete key-free operational conformance profile
conformance:
    uv run reasoning-kernel-conformance reasoning_kernel.conformance.reference:reference_suite

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
