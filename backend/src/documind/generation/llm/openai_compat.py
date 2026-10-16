"""Client for any OpenAI-compatible Chat Completions API. Groq is configured by
base_url + API key + model, and the same class works for OpenAI, Ollama or vLLM.

We call the HTTP API directly with httpx instead of an SDK. It's one endpoint, and
seeing the raw request and response is the point of a learning project.

Reliability (§11):
- every call has a timeout;
- timeouts, 429 and 5xx are retried with bounded exponential backoff, and a 429
  honors the provider's Retry-After header (capped);
- other 4xx errors are not retried (they won't fix themselves).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

from documind.domain.errors import LLMBadOutput, LLMError, LLMRateLimited, LLMTimeout
from documind.generation.llm.base import LLMResult, Message

RETRY_AFTER_CAP_S = 30.0
BACKOFF_BASE_S = 1.0


class LLMServerError(LLMError):
    retryable = True


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        structured_mode: str = "json_schema",
        temperature: float = 0.0,
        max_output_tokens: int = 1500,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        reasoning_effort: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_id = model
        self.structured_mode = structured_mode
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        self.reasoning_effort = reasoning_effort
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    def build_body(self, messages: list[Message], schema_name: str, schema: dict) -> dict:
        body: dict = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_output_tokens,
        }
        if self.structured_mode == "json_schema":
            # Strict mode: the provider constrains decoding so the output always matches the schema.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        else:
            # JSON mode: valid JSON is guaranteed, the schema is not. We validate ourselves.
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort and self.model_id.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def generate(self, messages: list[Message], schema_name: str, schema: dict) -> LLMResult:
        body = self.build_body(messages, schema_name, schema)
        for attempt in range(1, self.max_retries + 1):
            started = time.perf_counter()
            delay = BACKOFF_BASE_S * 2 ** (attempt - 1) * (0.5 + random.random())  # jitter
            try:
                response = self._client.post("/chat/completions", json=body)
            except httpx.TimeoutException:
                error: LLMError = LLMTimeout()
            except httpx.TransportError:
                error = LLMServerError("Network error talking to the LLM provider.")
            else:
                if response.status_code == 200:
                    return self._parse(response, started)
                error, delay = self._classify(response, delay)
            if not error.retryable or attempt == self.max_retries:
                raise error
            self._sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _classify(response: httpx.Response, default_delay: float) -> tuple[LLMError, float]:
        status = response.status_code
        if status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                delay = min(float(retry_after), RETRY_AFTER_CAP_S) if retry_after else default_delay
            except ValueError:
                delay = default_delay
            return LLMRateLimited(), delay
        if status >= 500:
            return LLMServerError(f"LLM provider returned HTTP {status}."), default_delay
        # Only the provider's error *code* is surfaced: messages may echo the prompt.
        try:
            code = response.json().get("error", {}).get("code") or "unknown"
        except ValueError:
            code = "unknown"
        if code == "json_validate_failed":
            return LLMBadOutput("Provider rejected output that did not match the schema."), default_delay
        return LLMError(f"LLM provider returned HTTP {status} ({code})."), default_delay

    def _parse(self, response: httpx.Response, started: float) -> LLMResult:
        data = response.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMBadOutput("Output was truncated (max tokens reached).")
        usage = data.get("usage") or {}
        return LLMResult(
            content=choice["message"].get("content") or "",
            model=data.get("model", self.model_id),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
