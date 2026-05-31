"""Live multi-provider round-trips (excluded by default; require API keys).

Run with ``just test-live`` or ``uv run pytest -m live``. Each provider must return a schema-valid
Plan through the single Reasoner interface — the fungibility corollary, exercised against real APIs.
A provider is skipped when its key is not configured (via env or ``.env``); set keys in ``.env``.
"""

from __future__ import annotations

import pytest

from reasoning_kernel.config import settings
from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider
from reasoning_kernel.reasoner.parse import call_structured
from reasoning_kernel.schemas.plan import Plan

pytestmark = pytest.mark.live

# Read from the loaded configuration (which sources .env), not just os.environ, so the live
# tests run identically under `just test-live` and a plain `uv run pytest -m live`.
_PROVIDER_SECRETS = {
    "anthropic": settings.anthropic_api_key,
    "openai": settings.openai_api_key,
    "deepseek": settings.deepseek_api_key,
}

_PROMPT = "Emit a Plan with run_id 'live', a single ConstStep id='a' value='hello', and final='a'."


@pytest.mark.parametrize("provider_name", list(_PROVIDER_SECRETS))
def test_provider_returns_valid_plan(provider_name: str) -> None:
    if not _PROVIDER_SECRETS[provider_name].get_secret_value():
        pytest.skip(f"{provider_name} key not configured")
    provider = get_llm_provider(provider_name)
    plan = call_structured(
        provider, _PROMPT, Plan, model=default_model_for(provider_name), max_tokens=1024
    )
    assert isinstance(plan, Plan)
    assert plan.steps  # the model produced at least one step


# Both current Deepseek models must round-trip through the same interface (the default and the
# more capable variant). Legacy names (deepseek-chat/-reasoner) are deprecated aliases of v4-flash.
_DEEPSEEK_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]


@pytest.mark.parametrize("model", _DEEPSEEK_MODELS)
def test_deepseek_model_returns_valid_plan(model: str) -> None:
    if not _PROVIDER_SECRETS["deepseek"].get_secret_value():
        pytest.skip("deepseek key not configured")
    provider = get_llm_provider("deepseek")
    plan = call_structured(provider, _PROMPT, Plan, model=model, max_tokens=1024)
    assert isinstance(plan, Plan)
    assert plan.steps
