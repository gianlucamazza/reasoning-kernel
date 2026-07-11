"""The provider factory resolves real providers by name and maps models from settings.

These are key-free: an unknown name fails closed before any SDK client is built, and
``default_model_for`` is a pure read over ``settings`` — neither path constructs a real provider.
"""

from __future__ import annotations

import pytest

from reasoning_kernel.config import settings
from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown or non-constructable"):
        get_llm_provider("nope")


def test_default_model_for_known_providers() -> None:
    assert default_model_for("anthropic") == settings.llm_model_anthropic
    assert default_model_for("openai") == settings.llm_model_openai
    assert default_model_for("deepseek") == settings.llm_model_deepseek


def test_default_model_for_fake_is_the_ignored_sentinel() -> None:
    assert default_model_for("fake") == "fake"


def test_default_model_for_unknown_provider_is_an_error() -> None:
    # A silent fallback would send an Anthropic model id to the wrong provider (opaque 404 at
    # call time); failing at resolution keeps the error next to the misconfiguration.
    with pytest.raises(ValueError, match="ignoto"):
        default_model_for("ignoto")


def test_roles_resolve_the_model_from_the_provider_name() -> None:
    # PLLM/QLLM with no model= resolve via default_model_for at construction time: an unknown
    # provider fails here, near the misconfiguration, not as a 404 deep inside a run.
    from reasoning_kernel.reasoner.fake import FakeProvider
    from reasoning_kernel.reasoner.roles import PLLM, QLLM

    PLLM(FakeProvider())  # "fake" resolves to the sentinel — no error
    QLLM(FakeProvider())

    class _UnknownProvider(FakeProvider):
        name = "mystery"

    with pytest.raises(ValueError, match="mystery"):
        PLLM(_UnknownProvider())
