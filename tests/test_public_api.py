"""The package root re-exports a stable public API (every ``__all__`` name resolves)."""

from __future__ import annotations

import reasoning_kernel as rk


def test_all_names_resolve() -> None:
    for name in rk.__all__:
        assert hasattr(rk, name), f"reasoning_kernel.{name} is in __all__ but not importable"


def test_key_building_blocks_are_exported() -> None:
    expected = {
        "Interpreter",
        "Gate",
        "EffectDispatcher",
        "ToolRegistry",
        "ToolSpec",
        "PLLM",
        "QLLM",
        "RunContext",
        "TrustedQuery",
        "RunLimits",
        "MergeStep",
        "VerifierVerdict",
    }
    assert expected <= set(rk.__all__)
