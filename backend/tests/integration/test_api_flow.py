"""End-to-end over HTTP with a real Postgres + pgvector, a fake embedder and a fake LLM."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from documind.db.tables import Chunk, Job
from tests.conftest import CONTRACT_PAGES, make_pdf

pytestmark = pytest.mark.integration


def upload(client, headers, path: Path, name: str | None = None):
    with path.open("rb") as f:
        return client.post("/v1/documents", headers=headers,
                           files={"file": (name or path.name, f, "application/octet-stream")})


def ingest(client, headers, container, path: Path) -> str:
    r = upload(client, headers, path)
    assert r.status_code == 202, r.text
    container.worker.run_until_empty()
    return r.json()["document_id"]


def ask(client, headers, question: str, **extra):
    return client.post("/v1/query", headers=headers, json={"question": question, **extra})


# ── Happy path ──────────────────────────────────────────

def test_pdf_upload_ingest_and_query_cites_correct_page(client, container, alice, contract_pdf):
    r = upload(client, alice, contract_pdf)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"

    assert container.worker.run_until_empty() == 1
    job = client.get(f"/v1/jobs/{body['job_id']}", headers=alice).json()
    assert (job["status"], job["progress"]) == ("succeeded", 1.0)

    doc = client.get(f"/v1/documents/{body['document_id']}", headers=alice).json()
    assert doc["status"] == "ready" and doc["page_count"] == 3 and doc["chunk_count"] >= 3
    assert doc["mime_type"] == "application/pdf" and doc["filename"] == "contrat.pdf"

    res = ask(client, alice, "Quel est le préavis de résiliation du contrat ?", debug=True)
    assert res.status_code == 200, res.text
    out = res.json()
    assert not out["abstained"] and out["answer"]
    top = out["citations"][0]
    assert top["document_id"] == body["document_id"]
    assert top["page_start"] == 3, "the termination clause is on page 3"
    assert out["diagnostics"]["dense"][0]["in_context"] is True
    assert out["model"]["prompt_version"] == "answer-fr-v3"

    page = client.get(f"/v1/documents/{body['document_id']}/pages/3", headers=alice).json()
    assert "Résiliation" in page["text"] and page["extraction_method"] == "text_layer"


def test_txt_upload_is_split_into_logical_pages(client, container, alice, tmp_path):
    path = tmp_path / "notes.txt"
    # Page 1 spans several chunks (40 tokens in tests). Chunks may cross a page boundary, so the
    # chunk holding the page-2 fact can start on page 1; its cited range must include page 2.
    page1 = " ".join(f"La réunion numéro {i} a porté sur le calendrier du projet." for i in range(8))
    path.write_text(page1 + "\fDeuxième partie sur le budget de 5 000 euros.", encoding="utf-8")
    doc_id = ingest(client, alice, container, path)
    doc = client.get(f"/v1/documents/{doc_id}", headers=alice).json()
    assert doc["status"] == "ready" and doc["page_count"] == 2
    top = ask(client, alice, "budget euros").json()["citations"][0]
    assert top["page_end"] == 2 and top["page_start"] <= 2
    assert "budget" in client.get(f"/v1/documents/{doc_id}/pages/2", headers=alice).json()["text"]


def test_list_documents_paginates(client, container, alice, tmp_path):
    for i in range(3):
        p = tmp_path / f"d{i}.txt"
        p.write_text(f"Document numéro {i}.", encoding="utf-8")
        assert upload(client, alice, p).status_code == 202
    first = client.get("/v1/documents?limit=2", headers=alice).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    rest = client.get(f"/v1/documents?limit=2&cursor={first['next_cursor']}", headers=alice).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    names = {d["filename"] for d in first["items"] + rest["items"]}
    assert names == {"d0.txt", "d1.txt", "d2.txt"}


# ── Validation ──────────────────────────────────────────

def test_duplicate_upload_returns_409_with_existing_id(client, alice, contract_pdf):
    first = upload(client, alice, contract_pdf).json()
    r = upload(client, alice, contract_pdf, name="copie.pdf")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "duplicate"
    assert r.json()["existing_document_id"] == first["document_id"]


def test_same_file_for_another_user_is_not_a_duplicate(client, alice, bob, contract_pdf):
    assert upload(client, alice, contract_pdf).status_code == 202
    assert upload(client, bob, contract_pdf).status_code == 202


def test_renamed_png_is_rejected(client, alice, tmp_path):
    fake_pdf = tmp_path / "facture.pdf"
    fake_pdf.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    r = upload(client, alice, fake_pdf)
    assert r.status_code == 415 and r.json()["code"] == "unsupported_file_type"


def test_oversize_file_is_rejected(client, alice, tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"a" * 250_000)  # test limit is 200 000 bytes
    r = upload(client, alice, big)
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"
    spool_dir = tmp_path / "blobs" / "tmp"
    assert not spool_dir.exists() or not any(spool_dir.iterdir()), "no temp file left behind"


def test_encrypted_pdf_fails_without_retry(client, container, alice, tmp_path):
    path = make_pdf(tmp_path / "secret.pdf", CONTRACT_PAGES, encrypt=True)
    r = upload(client, alice, path).json()
    container.worker.run_until_empty()
    doc = client.get(f"/v1/documents/{r['document_id']}", headers=alice).json()
    job = client.get(f"/v1/jobs/{r['job_id']}", headers=alice).json()
    assert (doc["status"], doc["error_code"]) == ("failed", "pdf_encrypted")
    assert (job["status"], job["attempts"], job["error_code"]) == ("failed", 1, "pdf_encrypted")


def test_missing_or_bad_api_key_is_401(client):
    r = client.get("/v1/documents")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.get("/v1/documents", headers={"Authorization": "Bearer dm_wrong"}).status_code == 401


def test_question_limits(client, alice):
    assert ask(client, alice, "x" * 2001).status_code == 400
    assert ask(client, alice, "ok", retrieval={"mode": "hybrid"}).status_code == 400
    assert ask(client, alice, "").status_code == 422


# ── Access control ──────────────────────────────────────

def test_owner_isolation(client, container, alice, bob, contract_pdf):
    r = upload(client, alice, contract_pdf).json()
    container.worker.run_until_empty()
    doc_id, job_id = r["document_id"], r["job_id"]

    for path in (f"/v1/documents/{doc_id}", f"/v1/documents/{doc_id}/pages/1", f"/v1/jobs/{job_id}"):
        assert client.get(path, headers=bob).status_code == 404
    assert client.delete(f"/v1/documents/{doc_id}", headers=bob).status_code == 404
    assert client.get("/v1/documents", headers=bob).json()["items"] == []

    # Bob's question matches Alice's document word for word, but retrieval is owner-scoped.
    out = ask(client, bob, "préavis de résiliation du contrat").json()
    assert out["abstained"] and out["abstention_reason"] == "no_relevant_evidence" and out["citations"] == []
    # Even naming Alice's document in the filter doesn't help.
    out = ask(client, bob, "préavis", filters={"document_ids": [doc_id]}).json()
    assert out["citations"] == []


def test_document_filter_restricts_retrieval(client, container, alice, contract_pdf, tmp_path):
    contract_id = ingest(client, alice, container, contract_pdf)
    other = tmp_path / "autre.txt"
    other.write_text("Le préavis de résiliation du bail est de trois mois.", encoding="utf-8")
    other_id = ingest(client, alice, container, other)
    out = ask(client, alice, "préavis de résiliation", filters={"document_ids": [other_id]}).json()
    assert {c["document_id"] for c in out["citations"]} == {other_id}
    assert contract_id != other_id


# ── Deletion ────────────────────────────────────────────

def test_delete_hides_immediately_then_removes_everything(client, container, alice, contract_pdf):
    r = upload(client, alice, contract_pdf).json()
    container.worker.run_until_empty()
    doc_id = r["document_id"]
    blob_files = [p for p in (container.settings.storage_dir).rglob("*") if p.is_file() and "tmp" not in p.parts]
    assert len(blob_files) == 1

    d = client.delete(f"/v1/documents/{doc_id}", headers=alice)
    assert d.status_code == 202
    # Before the worker runs: already invisible to retrieval.
    out = ask(client, alice, "préavis de résiliation").json()
    assert out["abstained"] and out["citations"] == []
    assert client.delete(f"/v1/documents/{doc_id}", headers=alice).status_code == 409

    container.worker.run_until_empty()
    assert client.get(f"/v1/documents/{doc_id}", headers=alice).status_code == 404
    with container.sf() as s:
        assert s.scalar(select(func.count()).select_from(Chunk)) == 0
    assert not blob_files[0].exists()
    job = client.get(f"/v1/jobs/{d.json()['job_id']}", headers=alice).json()
    assert job["status"] == "succeeded" and job["document_id"] is None


# ── Reliability ─────────────────────────────────────────

def test_transient_failure_is_retried_and_reindex_is_idempotent(client, container, alice, contract_pdf, monkeypatch):
    real = container.embedder.embed_documents
    calls = {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated GPU out-of-memory")
        return real(texts)

    monkeypatch.setattr(container.embedder, "embed_documents", flaky)
    r = upload(client, alice, contract_pdf).json()

    assert container.worker.run_once()
    job = client.get(f"/v1/jobs/{r['job_id']}", headers=alice).json()
    assert (job["status"], job["attempts"], job["error_code"]) == ("queued", 1, "RuntimeError")
    assert container.worker.run_once() is False, "backoff: not runnable yet"

    with container.engine.begin() as conn:  # fast-forward the backoff
        conn.execute(text("UPDATE jobs SET run_after = now()"))
    assert container.worker.run_once()
    assert client.get(f"/v1/jobs/{r['job_id']}", headers=alice).json()["status"] == "succeeded"

    def chunk_ids():
        with container.sf() as s:
            return set(s.scalars(select(Chunk.id).where(Chunk.document_id == r["document_id"])))

    before = chunk_ids()
    assert before
    assert client.post(f"/v1/documents/{r['document_id']}/reindex", headers=alice).status_code == 202
    container.worker.run_until_empty()
    assert chunk_ids() == before, "same config → same chunk ids, no duplicates"


def test_stale_running_job_is_reclaimed(client, container, alice, contract_pdf):
    r = upload(client, alice, contract_pdf).json()
    with container.engine.begin() as conn:  # simulate a worker that crashed mid-job an hour ago
        conn.execute(text("UPDATE jobs SET status='running', attempts=1, locked_by='dead', "
                          "locked_at = now() - interval '1 hour'"))
    assert container.worker.run_once()
    with container.sf() as s:
        job = s.get(Job, r["job_id"])
    assert job.status == "succeeded" and job.attempts == 2
