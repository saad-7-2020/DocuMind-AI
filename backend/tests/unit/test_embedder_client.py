import json
import math

import httpx
import numpy as np
import pytest

from documind.domain.errors import EmbeddingError, EmbeddingUnavailable
from documind.embedding.openai_compat import OpenAICompatEmbedder

DIM = 8


def vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.normal(size=DIM).tolist()


def ok_response(request: httpx.Request, shuffle: bool = False) -> httpx.Response:
    body = json.loads(request.content)
    data = [{"index": i, "embedding": vec(hash(t) % 1000)} for i, t in enumerate(body["input"])]
    if shuffle:
        data.reverse()
    return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 1}})


def make(handler, sleeps=None, **kw) -> OpenAICompatEmbedder:
    return OpenAICompatEmbedder(
        base_url="https://api.example.com/v1", api_key="secret-key", model="m-1", dim=kw.pop("dim", DIM),
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else lambda s: None), **kw,
    )


def test_request_shape_auth_and_per_kind_extra_fields():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return ok_response(request)

    emb = make(handler, query_extra={"task": "retrieval.query"}, document_extra={"task": "retrieval.passage"})
    emb.embed_documents(["un", "deux"])
    emb.embed_query("question ?")

    url, auth, body = seen[0]
    assert url == "https://api.example.com/v1/embeddings" and auth == "Bearer secret-key"
    assert body == {"model": "m-1", "input": ["un", "deux"], "task": "retrieval.passage"}
    assert seen[1][2] == {"model": "m-1", "input": ["question ?"], "task": "retrieval.query"}


def test_vectors_are_normalized_and_ordered_even_if_provider_shuffles():
    texts = ["a", "b", "c"]
    plain = make(lambda r: ok_response(r)).embed_documents(texts)
    shuffled = make(lambda r: ok_response(r, shuffle=True)).embed_documents(texts)
    assert np.allclose(np.linalg.norm(plain, axis=1), 1.0)
    assert np.allclose(plain, shuffled), "results must be re-ordered by the provider's `index`"


def test_batching_splits_requests():
    sizes = []

    def handler(request):
        sizes.append(len(json.loads(request.content)["input"]))
        return ok_response(request)

    out = make(handler, batch_size=2).embed_documents([f"t{i}" for i in range(5)])
    assert sizes == [2, 2, 1] and out.shape == (5, DIM)


def test_empty_input_makes_no_request():
    def handler(request):
        raise AssertionError("no request expected")

    assert make(handler).embed_documents([]).shape == (0, DIM)


def test_dimension_mismatch_is_a_clear_error():
    with pytest.raises(EmbeddingError) as exc:
        make(lambda r: ok_response(r), dim=16).embed_query("x")
    assert "8-dimensional" in exc.value.detail and "EMBEDDING_DIM=16" in exc.value.detail


def test_send_dimensions_option():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return ok_response(request)

    make(handler, send_dimensions=True).embed_query("x")
    assert seen["dimensions"] == DIM


def test_rate_limit_honors_retry_after_then_succeeds():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return ok_response(request)

    make(handler, sleeps).embed_query("x")
    assert len(calls) == 2 and sleeps == [3.0]


def test_timeouts_are_retried_a_bounded_number_of_times():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(EmbeddingUnavailable):
        make(handler, max_retries=3).embed_query("x")
    assert len(calls) == 3


def test_bad_credentials_are_not_retried_and_do_not_leak_the_body():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"detail": "bad key; you sent: document text here"})

    with pytest.raises(EmbeddingError) as exc:
        make(handler).embed_query("x")
    assert len(calls) == 1 and "document text" not in exc.value.detail and "HTTP 401" in exc.value.detail
    assert not isinstance(exc.value, EmbeddingUnavailable)


def test_token_estimate_is_conservative_for_french():
    emb = make(lambda r: ok_response(r))
    text = "Le préavis de résiliation est de trente jours."
    assert emb.count_tokens(text) == math.ceil(len(text) / 3.2)
    assert emb.count_tokens(text) > len(text) / 4, "leans high: chunks get smaller, never truncated"
    assert emb.count_tokens("") == 0
    assert emb.tokenizer_id == "chars/3.2"
