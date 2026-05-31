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


def test_default_model_for_unknown_falls_back_to_anthropic() -> None:
    assert default_model_for("ignoto") == settings.llm_model_anthropic
