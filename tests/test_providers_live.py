"""Live multi-provider round-trips (excluded by default; require API keys).

Run with ``just test-live`` or ``uv run pytest -m live``. Each provider must return a schema-valid
Plan through the single Reasoner interface — the fungibility corollary, exercised against real APIs.
Without ``RK_LIVE_PROVIDERS``, a provider is skipped when its key is absent. With the selector,
every listed provider and key is required while all other providers are explicitly excluded.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, SecretStr

from reasoning_kernel.config import settings
from reasoning_kernel.kernel.session import RunSession
from reasoning_kernel.memory.sink import SQLiteTraceSink
from reasoning_kernel.reasoner.factory import default_model_for, get_llm_provider
from reasoning_kernel.reasoner.fake import FakeProvider
from reasoning_kernel.reasoner.parse import call_structured
from reasoning_kernel.reasoner.roles import PLLM, QLLM
from reasoning_kernel.schemas.capability import Capability, CapabilitySet, EffectLevel
from reasoning_kernel.schemas.ids import RunId, StepId
from reasoning_kernel.schemas.plan import ArgRef, ConstStep, Plan, QuarantineParseStep, ToolCallStep
from reasoning_kernel.schemas.policy import RunContext, TrustedQuery, VerifierVerdict
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.tools.registry import ToolRegistry

# Read from the loaded configuration (which sources .env), not just os.environ, so the live
# tests run identically under `just test-live` and a plain `uv run pytest -m live`.
_PROVIDER_SECRETS = {
    "anthropic": settings.anthropic_api_key,
    "openai": settings.openai_api_key,
    "deepseek": settings.deepseek_api_key,
}

_selection = os.environ.get("RK_LIVE_PROVIDERS")
_SELECTED_PROVIDERS = (
    frozenset(name.strip() for name in _selection.split(",") if name.strip())
    if _selection is not None
    else None
)
if _SELECTED_PROVIDERS is not None:
    unknown = _SELECTED_PROVIDERS.difference(_PROVIDER_SECRETS)
    if not _SELECTED_PROVIDERS or unknown:
        raise RuntimeError("RK_LIVE_PROVIDERS must list known provider names")

_PROMPT = "Emit a Plan with run_id 'live', a single ConstStep id='a' value='hello', and final='a'."


def _require_provider(provider_name: str) -> None:
    if _SELECTED_PROVIDERS is not None and provider_name not in _SELECTED_PROVIDERS:
        pytest.skip(f"{provider_name} excluded by RK_LIVE_PROVIDERS")
    if not _PROVIDER_SECRETS[provider_name].get_secret_value():
        if _SELECTED_PROVIDERS is not None:
            pytest.fail(f"required {provider_name} key not configured")
        pytest.skip(f"{provider_name} key not configured")


@pytest.mark.live
@pytest.mark.parametrize("provider_name", list(_PROVIDER_SECRETS))
def test_provider_returns_valid_plan(provider_name: str) -> None:
    _require_provider(provider_name)
    provider = get_llm_provider(provider_name)
    plan = call_structured(
        provider, _PROMPT, Plan, model=default_model_for(provider_name), max_tokens=1024
    )
    assert isinstance(plan, Plan)
    assert plan.steps  # the model produced at least one step


# Both current Deepseek models must round-trip through the same interface (the default and the
# more capable variant). Legacy names (deepseek-chat/-reasoner) are deprecated aliases of v4-flash.
_DEEPSEEK_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]


@pytest.mark.live
@pytest.mark.parametrize("model", _DEEPSEEK_MODELS)
def test_deepseek_model_returns_valid_plan(model: str) -> None:
    _require_provider("deepseek")
    provider = get_llm_provider("deepseek")
    plan = call_structured(provider, _PROMPT, Plan, model=model, max_tokens=1024)
    assert isinstance(plan, Plan)
    assert plan.steps


class _Summary(BaseModel):
    text: str


class _SendInput(BaseModel):
    to: str
    body: str


class _SendOutput(BaseModel):
    ok: bool


class _RecipientPolicy:
    def may_declassify(self, tool, named_args, ctx):
        recipient = named_args.get("to")
        allowed = recipient is not None and recipient.value == ctx.user
        return VerifierVerdict(allowed=allowed, reason="recipient is requesting user")


@pytest.mark.live
@pytest.mark.parametrize("provider_name", ["openai", "deepseek"])
def test_operational_session_with_live_quarantine_provider(provider_name: str, tmp_path) -> None:
    """Exercise Q-LLM, normalized WRITE and durable redacted audit; no external tool effect."""
    _require_provider(provider_name)
    run_id = RunId(f"live-operational-{provider_name}")
    user = "user@example.com"
    plan = Plan(
        run_id=run_id,
        steps=[
            ConstStep(id=StepId("raw"), value="The project is ready for review."),
            QuarantineParseStep(
                id=StepId("summary"),
                source=ArgRef(ref=StepId("raw")),
                schema_ref="summary",
                instruction="Summarize this sentence in five words or fewer.",
            ),
            ToolCallStep(
                id=StepId("send"),
                tool="send",
                args={
                    "to": user,
                    "body": ArgRef(ref=StepId("summary"), path="text"),
                },
            ),
        ],
        final=StepId("send"),
    )
    sent: list[_SendInput] = []
    registry = ToolRegistry()
    cap = Capability(name="mail.send")
    grant = CapabilitySet(granted=frozenset({cap}))
    registry.register(
        ToolSpec(
            name="send",
            input_schema=_SendInput,
            output_schema=_SendOutput,
            required_caps=frozenset({cap}),
            effect_level=EffectLevel.WRITE,
            args_leave_boundary=True,
        ),
        lambda value: sent.append(_SendInput.model_validate(value)) or _SendOutput(ok=True),
    )
    real_provider = get_llm_provider(provider_name)
    ctx = RunContext(run_id=run_id, user=user, query=TrustedQuery(text="Summarize safely"))
    audit_path = tmp_path / f"{provider_name}.sqlite"
    with SQLiteTraceSink(audit_path) as sink:
        result = RunSession(
            ctx=ctx,
            registry=registry,
            grant=grant,
            declass=_RecipientPolicy(),
            planner=PLLM(FakeProvider({"Plan": plan}), grant=grant),
            quarantine=QLLM(real_provider, model=default_model_for(provider_name)),
            q_schemas={"summary": _Summary},
            sink=sink,
        ).run()
        persisted = sink.read(run_id)
    assert result.status == "succeeded"
    assert len(sent) == 1 and sent[0].to == user
    serialized = "".join(event.model_dump_json() for event in persisted)
    assert "The project is ready" not in serialized
    assert sent[0].body not in serialized


def test_selected_live_provider_requires_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(globals(), "_SELECTED_PROVIDERS", frozenset({"deepseek"}))
    monkeypatch.setitem(_PROVIDER_SECRETS, "deepseek", SecretStr(""))
    with pytest.raises(pytest.fail.Exception, match="required deepseek key"):
        _require_provider("deepseek")


def test_unselected_live_provider_is_explicitly_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(globals(), "_SELECTED_PROVIDERS", frozenset({"deepseek"}))
    with pytest.raises(pytest.skip.Exception, match="excluded by RK_LIVE_PROVIDERS"):
        _require_provider("openai")
