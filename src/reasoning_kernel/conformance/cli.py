"""Command-line entry point for host conformance suites."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from reasoning_kernel.conformance.models import ConformanceSuite
from reasoning_kernel.conformance.runner import ConformanceConfigurationError, run_conformance


def _load_factory(reference: str) -> Callable[[], object]:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ConformanceConfigurationError("factory must use module:attribute syntax")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise ConformanceConfigurationError("factory is not callable")
    return factory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Reasoning Kernel host conformance")
    parser.add_argument("factory", help="trusted host suite factory as module:attribute")
    parser.add_argument("--output", type=Path, help="write the sanitized JSON report to this path")
    args = parser.parse_args(argv)

    try:
        candidate = _load_factory(args.factory)()
        if not isinstance(candidate, ConformanceSuite):
            raise ConformanceConfigurationError("factory did not return ConformanceSuite")
        report = run_conformance(candidate)
        rendered = report.model_dump_json(indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            args.output.write_text(rendered, encoding="utf-8")
            outcome = "PASS" if report.passed else "FAIL"
            print(f"{outcome} {report.profile} ({len(report.cases)} cases)")
        return 0 if report.passed else 1
    except Exception:
        print("conformance configuration or runner error", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
