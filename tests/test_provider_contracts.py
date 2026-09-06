"""SDK-shaped fixtures exercise fallback, truncation and rejection without API calls."""

from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from reasoning_kernel import ReasonerError, TransportError
from reasoning_kernel.reasoner.anthropic import AnthropicProvider
from reasoning_kernel.reasoner.deepseek import DeepseekProvider
from reasoning_kernel.reasoner.openai import OpenAIProvider


class Output(BaseModel):
    x: int


def completion(*, content='{"x": 7}', parsed=None, reason="stop", refusal=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=reason,
                message=SimpleNamespace(content=content, parsed=parsed, refusal=refusal),
            )
        ],
        usage=None,
        model="test",
    )


def bad_request(param=None, body=None):
    return openai.BadRequestError(
        "response_format SECRET unstructured message",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.test")),
        body=body if body is not None else {"param": param},
    )


class Completions:
    def __init__(self, first, fallback=None):
        self.first, self.fallback = first, fallback
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append("parse")
        if isinstance(self.first, Exception):
            raise self.first
        return self.first

    def create(self, **kwargs):
        self.calls.append("create")
        assert kwargs["response_format"] == {"type": "json_object"}
        if isinstance(self.fallback, Exception):
            raise self.fallback
        return self.fallback


def parse(first, fallback=None, provider_cls=OpenAIProvider):
    api = Completions(first, fallback)
    provider = provider_cls(client=SimpleNamespace(chat=SimpleNamespace(completions=api)))
    return provider, api


def invoke(provider):
    return provider.parse(prompt="p", schema=Output, system=None, model="test", max_tokens=32)


@pytest.mark.parametrize(
    "body",
    [
        {"param": "response_format"},
        {"error": {"param": "response_format.json_schema"}},
    ],
)
def test_structured_error_gets_one_validated_fallback(body):
    provider, api = parse(bad_request(body=body), completion())
    assert invoke(provider).data == Output(x=7)
    assert api.calls == ["parse", "create"]


def test_deepseek_uses_validated_json_mode_directly():
    provider, api = parse(None, completion(), DeepseekProvider)
    assert invoke(provider).data == Output(x=7)
    assert api.calls == ["create"]


def test_message_substring_does_not_trigger_fallback():
    provider, api = parse(bad_request(param="model"))
    with pytest.raises(TransportError) as error:
        invoke(provider)
    assert "SECRET" not in str(error.value)
    assert api.calls == ["parse"]


def test_fallback_failure_is_terminal():
    provider, api = parse(
        bad_request(param="response_format"), bad_request(param="response_format")
    )
    with pytest.raises(TransportError):
        invoke(provider)
    assert api.calls == ["parse", "create"]


@pytest.mark.parametrize(
    "response,match",
    [
        (completion(reason="length"), "truncated"),
        (completion(reason="content_filter"), "refused"),
        (completion(refusal="SECRET"), "refused"),
        (completion(content=""), "empty"),
        (completion(content='{"x": "bad"}'), "invalid"),
    ],
)
def test_json_fallback_handles_unusable_responses(response, match):
    provider, _ = parse(bad_request(param="response_format"), response)
    with pytest.raises(ReasonerError, match=match):
        invoke(provider)


@pytest.mark.parametrize("reason", ["length", "content_filter"])
def test_strict_rejects_truncated_or_filtered_parsed_data(reason):
    provider, _ = parse(completion(parsed=Output(x=1), reason=reason))
    with pytest.raises(ReasonerError):
        invoke(provider)


@pytest.mark.parametrize(
    "error",
    [
        openai.LengthFinishReasonError(completion=completion()),
        openai.ContentFilterFinishReasonError(),
    ],
)
def test_sdk_parse_exceptions_are_normalized(error):
    provider, _ = parse(error)
    with pytest.raises(ReasonerError):
        invoke(provider)


@pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
def test_anthropic_rejects_incomplete_output(reason):
    response = SimpleNamespace(
        parsed_output=Output(x=1), stop_reason=reason, usage=None, model="test"
    )
    provider = AnthropicProvider(
        client=SimpleNamespace(messages=SimpleNamespace(parse=lambda **_: response))
    )
    with pytest.raises(ReasonerError):
        invoke(provider)
