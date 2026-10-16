import json

import httpx
import pytest

from documind.domain.errors import LLMError, LLMTimeout
from documind.generation.llm.openai_compat import OpenAICompatLLM
from documind.generation.prompts import ANSWER_SCHEMA

OK_BODY = {
    "model": "openai/gpt-oss-120b",
    "choices": [{"message": {"content": '{"answer": "x"}'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
}


def make_llm(handler, sleeps=None, **kw) -> OpenAICompatLLM:
    return OpenAICompatLLM(
        base_url="https://api.groq.com/openai/v1", api_key="test-key", model=kw.pop("model", "openai/gpt-oss-120b"),
        transport=httpx.MockTransport(handler), sleep=(sleeps.append if sleeps is not None else lambda s: None),
        reasoning_effort="low", **kw,
    )


def test_request_uses_strict_json_schema_and_parses_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    result = make_llm(handler).generate([{"role": "user", "content": "q"}], "grounded_answer", ANSWER_SCHEMA)
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    fmt = seen["body"]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert seen["body"]["reasoning_effort"] == "low" and seen["body"]["temperature"] == 0.0
    assert (result.content, result.input_tokens, result.output_tokens) == ('{"answer": "x"}', 120, 30)


def test_json_object_mode_and_no_reasoning_param_for_llama():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    make_llm(handler, model="llama-3.3-70b-versatile", structured_mode="json_object").generate(
        [{"role": "user", "content": "q"}], "a", ANSWER_SCHEMA)
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in seen["body"]


def test_429_honors_retry_after_then_succeeds():
    calls, sleeps = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"code": "rate_limit_exceeded"}})
        return httpx.Response(200, json=OK_BODY)

    make_llm(handler, sleeps).generate([{"role": "user", "content": "q"}], "a", ANSWER_SCHEMA)
    assert len(calls) == 2 and sleeps == [2.0]


def test_timeouts_are_retried_a_bounded_number_of_times():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMTimeout):
        make_llm(handler, max_retries=3).generate([{"role": "user", "content": "q"}], "a", ANSWER_SCHEMA)
    assert len(calls) == 3


def test_client_errors_are_not_retried_and_hide_provider_message():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"code": "model_not_found", "message": "secret prompt echo"}})

    with pytest.raises(LLMError) as exc:
        make_llm(handler).generate([{"role": "user", "content": "q"}], "a", ANSWER_SCHEMA)
    assert len(calls) == 1
    assert "model_not_found" in exc.value.detail and "secret" not in exc.value.detail
