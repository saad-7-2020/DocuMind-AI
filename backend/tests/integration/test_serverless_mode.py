"""Serverless hosting (Vercel): no background worker, so jobs run inside the requests that create them."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

from documind.config import get_settings
from documind.container import build_container
from tests.conftest import _make_user

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def inline_client(settings):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    container = build_container(settings.model_copy(update={"inline_jobs": True}))
    with container.engine.begin() as conn:
        conn.execute(text("TRUNCATE users, documents, jobs, query_logs, eval_runs CASCADE"))
    headers = _make_user(container, "inline@example.com")
    with TestClient(create_app(container)) as client:
        yield client, container, headers
    container.close()


def upload(client, headers, path: Path):
    with path.open("rb") as f:
        return client.post("/v1/documents", headers=headers, files={"file": (path.name, f)})


def test_upload_is_indexed_before_the_response_returns(inline_client, contract_pdf):
    client, container, headers = inline_client
    accepted = upload(client, headers, contract_pdf).json()
    # No worker was run by the test: the request itself did the work.
    job = client.get(f"/v1/jobs/{accepted['job_id']}", headers=headers).json()
    assert (job["status"], job["progress"]) == ("succeeded", 1.0)
    doc = client.get(f"/v1/documents/{accepted['document_id']}", headers=headers).json()
    assert doc["status"] == "ready" and doc["chunk_count"] >= 1
    answer = client.post("/v1/query", headers=headers, json={"question": "préavis de résiliation"}).json()
    assert answer["citations"]


def test_delete_is_completed_inside_the_request(inline_client, contract_pdf):
    client, container, headers = inline_client
    doc_id = upload(client, headers, contract_pdf).json()["document_id"]
    assert client.delete(f"/v1/documents/{doc_id}", headers=headers).status_code == 202
    assert client.get(f"/v1/documents/{doc_id}", headers=headers).status_code == 404


def test_a_failed_job_is_retried_when_the_client_polls(inline_client, contract_pdf, monkeypatch):
    client, container, headers = inline_client
    real, calls = container.embedder.embed_documents, {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated provider hiccup")
        return real(texts)

    monkeypatch.setattr(container.embedder, "embed_documents", flaky)
    accepted = upload(client, headers, contract_pdf).json()
    job = client.get(f"/v1/jobs/{accepted['job_id']}", headers=headers).json()
    assert (job["status"], job["error_code"]) == ("queued", "RuntimeError"), "failed once, waiting for backoff"

    with container.engine.begin() as conn:  # the backoff time passes
        conn.execute(text("UPDATE jobs SET run_after = now()"))
    job = client.get(f"/v1/jobs/{accepted['job_id']}", headers=headers).json()
    assert job["status"] == "succeeded", "the poll ran the due retry"


def test_health_reports_the_upload_limit(inline_client):
    client, container, _ = inline_client
    assert client.get("/health/ready").json()["max_upload_bytes"] == container.settings.max_upload_bytes


def test_inline_mode_is_off_by_default(client, alice, contract_pdf):
    accepted = upload(client, alice, contract_pdf).json()
    job = client.get(f"/v1/jobs/{accepted['job_id']}", headers=alice).json()
    assert job["status"] == "queued", "without inline mode only a worker processes jobs"


def test_vercel_entrypoint_exposes_a_working_app(monkeypatch, migrated_db_url, tmp_path):
    """backend/index.py is what Vercel loads: it must export `app` and serve requests."""
    from fastapi.testclient import TestClient

    for key, value in {
        "DATABASE_URL": migrated_db_url, "EMBEDDER": "fake", "LLM_PROVIDER": "fake", "INLINE_JOBS": "true",
        "STORAGE_DIR": str(tmp_path), "DB_POOL_SIZE": "2", "DB_MAX_OVERFLOW": "1",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        spec = importlib.util.spec_from_file_location("vercel_index", BACKEND / "index.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            assert client.get("/health/live").json() == {"status": "ok"}
            assert client.get("/health/ready").status_code == 200
            assert client.get("/v1/documents").status_code == 401  # routes are mounted and auth is enforced
    finally:
        get_settings.cache_clear()
