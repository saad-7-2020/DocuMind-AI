"""The production-shaped configuration, exercised against a real Postgres with fake external
services: Supabase Storage and a hosted embedding API are replaced by in-process HTTP fakes,
the ingestion worker runs as a thread of the API process, and the frontend is on another origin."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from documind.config import Settings
from documind.container import Container, build_container
from documind.embedding.fake import HashEmbedder
from documind.embedding.openai_compat import OpenAICompatEmbedder
from documind.ingestion.storage import SupabaseBlobStore
from tests.conftest import _make_user
from tests.unit.test_supabase_storage import SERVICE_KEY, FakeSupabase

pytestmark = pytest.mark.integration

ORIGIN = "https://documind.vercel.app"


@pytest.fixture
def make_container(settings: Settings):
    created: list[Container] = []

    def _make(**overrides) -> Container:
        c = build_container(settings.model_copy(update=overrides))
        with c.engine.begin() as conn:
            conn.execute(text("TRUNCATE users, documents, jobs, query_logs, eval_runs CASCADE"))
        created.append(c)
        return c

    yield _make
    for c in created:
        c.close()


def wait_for(predicate, timeout_s: float = 20.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


def upload(client, headers, path: Path):
    with path.open("rb") as f:
        return client.post("/v1/documents", headers=headers, files={"file": (path.name, f)})


# ── CORS (frontend on Vercel, API on Render) ─────────────

def test_cors_allows_only_the_configured_origin(make_container):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    container = make_container(cors_origins=[ORIGIN])
    with TestClient(create_app(container)) as client:
        preflight = {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        ok = client.options("/v1/query", headers={"Origin": ORIGIN, **preflight})
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == ORIGIN
        assert "authorization" in ok.headers["access-control-allow-headers"].lower()
        assert "access-control-allow-credentials" not in ok.headers

        evil = client.options("/v1/query", headers={"Origin": "https://evil.example", **preflight})
        assert "access-control-allow-origin" not in evil.headers

        # Errors are readable cross-origin too (a 401 must not look like a network failure).
        err = client.get("/v1/documents", headers={"Origin": ORIGIN})
        assert err.status_code == 401 and err.headers["access-control-allow-origin"] == ORIGIN
        assert "x-request-id" in err.headers["access-control-expose-headers"].lower()


def test_no_cors_headers_when_not_configured(client):
    r = client.get("/health/live", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in r.headers


# ── Worker thread inside the API process ─────────────────

def test_worker_thread_indexes_uploads_without_a_separate_process(make_container, contract_pdf):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    container = make_container(run_worker_in_api=True, worker_poll_interval_s=0.05)
    headers = _make_user(container, "thread@example.com")
    with TestClient(create_app(container)) as client:
        accepted = upload(client, headers, contract_pdf).json()
        def finished():
            job = client.get(f"/v1/jobs/{accepted['job_id']}", headers=headers).json()
            return job if job["status"] == "succeeded" else None

        assert wait_for(finished)["progress"] == 1.0
        answer = client.post("/v1/query", headers=headers, json={"question": "préavis de résiliation"}).json()
        assert answer["citations"][0]["page_start"] == 3


# ── Supabase Storage + hosted embeddings, end to end ─────

def test_full_flow_with_supabase_storage_and_hosted_embeddings(make_container, contract_pdf):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    # A fake "hosted embedding API" that returns the hash embedder's vectors in the OpenAI format.
    hash_embedder = HashEmbedder(1024)
    embed_calls: list[dict] = []

    def embeddings_api(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        embed_calls.append(body)
        vectors = hash_embedder.embed_documents(body["input"]).tolist()
        return httpx.Response(200, json={"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})

    hosted = OpenAICompatEmbedder(
        "https://api.example.com/v1", "key", "hosted-model", 1024, query_extra={"task": "retrieval.query"},
        document_extra={"task": "retrieval.passage"}, transport=httpx.MockTransport(embeddings_api),
    )
    fake_storage = FakeSupabase()
    store = SupabaseBlobStore("https://abc.supabase.co", SERVICE_KEY, "documents",
                              transport=httpx.MockTransport(fake_storage), sleep=lambda s: None)

    settings = make_container().settings
    container = build_container(settings, embedder=hosted)
    container.blobs = container.indexing.blobs = store  # swap the local disk for "Supabase"
    headers = _make_user(container, "cloud@example.com")
    try:
        with TestClient(create_app(container)) as client:
            accepted = upload(client, headers, contract_pdf).json()
            assert len(fake_storage.objects) == 1, "the file went to object storage"
            kept_on_disk = [p for p in settings.storage_dir.rglob("*") if p.is_file() and "tmp" not in p.parts]
            assert kept_on_disk == [], "nothing is kept on the local disk"

            assert container.worker.run_until_empty() == 1
            doc = client.get(f"/v1/documents/{accepted['document_id']}", headers=headers).json()
            assert doc["status"] == "ready" and doc["chunk_count"] >= 1

            question = "notifié par lettre recommandée avec accusé de réception"  # only on page 3
            out = client.post("/v1/query", headers=headers, json={"question": question, "debug": True}).json()
            assert out["citations"][0]["page_end"] == 3
            assert out["model"]["embedder"] == "hosted-model"

            kinds = [c.get("task") for c in embed_calls]
            assert "retrieval.passage" in kinds and kinds[-1] == "retrieval.query"

            assert client.delete(f"/v1/documents/{accepted['document_id']}", headers=headers).status_code == 202
            container.worker.run_until_empty()
            assert fake_storage.objects == {}, "deleting a document removes its file from object storage"
    finally:
        container.close()


# ── Database hardening ───────────────────────────────────

def test_row_level_security_is_enabled_on_every_table(container):
    with container.engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.relname, c.relrowsecurity FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
        """)).all()
    assert len(rows) >= 11
    assert [name for name, enabled in rows if not enabled] == []


def test_root_gives_a_friendly_pointer_instead_of_not_found(client):
    r = client.get("/")
    assert r.status_code == 200 and r.json()["docs"] == "/docs" and r.json()["health"] == "/health/ready"
