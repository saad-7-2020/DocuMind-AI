"""Hosted embeddings through any OpenAI-compatible `POST {base_url}/embeddings` endpoint
(Jina, OpenAI, Mistral, …). Used in production, where the local bge-m3 model doesn't fit.

Things that are provider-specific are configuration, not code:
- extra body fields per kind of text (`EMBEDDING_QUERY_EXTRA` / `EMBEDDING_DOCUMENT_EXTRA`),
  e.g. Jina's `{"task": "retrieval.query"}` vs `{"task": "retrieval.passage"}`: the same
  asymmetric query/passage idea as the local model's prefixes;
- whether to request a truncated size (`EMBEDDING_SEND_DIMENSIONS`).

Reliability matches the LLM client: timeouts, bounded retries with jitter, `Retry-After` honored on 429.
Errors never include response bodies (providers may echo the input text).
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import numpy as np

from documind.domain.errors import EmbeddingError, EmbeddingUnavailable

RETRY_AFTER_CAP_S = 30.0
BACKOFF_BASE_S = 1.0


class OpenAICompatEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        batch_size: int = 16,
        query_extra: dict[str, Any] | None = None,
        document_extra: dict[str, Any] | None = None,
        send_dimensions: bool = False,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        chars_per_token: float = 3.2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_id = model
        self.dim = dim
        self.tokenizer_id = f"chars/{chars_per_token}"
        self.batch_size = max(1, batch_size)
        self.query_extra = query_extra or {}
        self.document_extra = document_extra or {}
        self.send_dimensions = send_dimensions
        self.max_retries = max_retries
        self.chars_per_token = chars_per_token
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    # ── Embedder interface ───────────────────────────────
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(list(texts), self.document_extra)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], self.query_extra)[0]

    def count_tokens(self, text: str) -> int:
        """No local tokenizer for a hosted model, so estimate. The estimate leans high (3.2 chars per
        token for French), which makes chunks slightly smaller rather than risking truncation."""
        return math.ceil(len(text) / self.chars_per_token) if text else 0

    # ── Implementation ───────────────────────────────────
    def _embed(self, texts: list[str], extra: dict[str, Any]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), np.float32)
        rows: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            rows.extend(self._request(texts[i : i + self.batch_size], extra))
        vectors = np.asarray(rows, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms  # cosine similarity == dot product, whatever the provider returns

    def _request(self, batch: list[str], extra: dict[str, Any]) -> list[list[float]]:
        body: dict[str, Any] = {"model": self.model_id, "input": batch, **extra}
        if self.send_dimensions:
            body["dimensions"] = self.dim
        for attempt in range(1, self.max_retries + 1):
            delay = BACKOFF_BASE_S * 2 ** (attempt - 1) * (0.5 + random.random())
            try:
                response = self._client.post("/embeddings", json=body)
            except httpx.TimeoutException:
                error: EmbeddingError = EmbeddingUnavailable("Embedding provider timed out.")
            except httpx.TransportError:
                error = EmbeddingUnavailable("Network error talking to the embedding provider.")
            else:
                if response.status_code == 200:
                    return self._parse(response, expected=len(batch))
                error, delay = self._classify(response, delay)
            if not error.retryable or attempt == self.max_retries:
                raise error
            self._sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _classify(response: httpx.Response, default_delay: float) -> tuple[EmbeddingError, float]:
        status = response.status_code
        if status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                delay = min(float(retry_after), RETRY_AFTER_CAP_S) if retry_after else default_delay
            except ValueError:
                delay = default_delay
            return EmbeddingUnavailable("Embedding provider rate limit reached."), delay
        if status >= 500:
            return EmbeddingUnavailable(f"Embedding provider returned HTTP {status}."), default_delay
        if status in (401, 403):
            return EmbeddingError(f"Embedding provider rejected the credentials (HTTP {status})."), default_delay
        return EmbeddingError(f"Embedding provider returned HTTP {status}."), default_delay

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError("Unexpected response format from the embedding provider.") from e
        if len(vectors) != expected:
            raise EmbeddingError(f"Provider returned {len(vectors)} embeddings for {expected} inputs.")
        for v in vectors:
            if len(v) != self.dim:
                raise EmbeddingError(
                    f"Provider returned {len(v)}-dimensional vectors but EMBEDDING_DIM={self.dim}. "
                    "Check the model name, or set EMBEDDING_SEND_DIMENSIONS if the provider supports it."
                )
        return vectors
