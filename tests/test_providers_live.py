"""Live multi-provider round-trips (excluded by default; require API keys).

Run with: ``uv run pytest -m live``. Each provider must return a schema-valid Plan through the
single Reasoner interface — the fungibility corollary, exercised against real APIs.
"""

from __future__ import annotations

import os

import pytest

from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider
from reasoning_kernel.reasoner.parse import call_structured
from reasoning_kernel.schemas.plan import Plan

pytestmark = pytest.mark.live

_PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_PROMPT = "Emit a Plan with run_id 'live', a single ConstStep id='a' value='hello', and final='a'."


@pytest.mark.parametrize("provider_name", list(_PROVIDER_KEYS))
def test_provider_returns_valid_plan(provider_name: str) -> None:
    env_key = _PROVIDER_KEYS[provider_name]
    if not os.environ.get(env_key):
        pytest.skip(f"{env_key} not set")
    provider = get_llm_provider(provider_name)
    plan = call_structured(
        provider, _PROMPT, Plan, model=default_model_for(provider_name), max_tokens=1024
    )
    assert isinstance(plan, Plan)
    assert plan.steps  # the model produced at least one step
