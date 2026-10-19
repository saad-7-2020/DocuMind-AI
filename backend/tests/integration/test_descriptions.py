"""Every indexed document gets a summary, keywords and suggested questions; failures never block an upload."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from documind.container import build_container
from documind.generation.llm.fake import ScriptedLLM
from tests.conftest import _make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def make(settings):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    made = []

    def _make(light_llm=None):
        container = build_container(settings, light_llm=light_llm)
        with container.engine.begin() as conn:
            conn.execute(text("TRUNCATE users, documents, jobs, query_logs, eval_runs CASCADE"))
        client = TestClient(create_app(container))
        client.__enter__()
        made.append((client, container))
        return client, container, _make_user(container, "doc@example.com")

    yield _make
    for client, container in made:
        client.__exit__(None, None, None)
        container.close()


def upload(client, headers, path):
    with path.open("rb") as f:
        return client.post("/v1/documents", headers=headers, files={"file": (path.name, f)}).json()["document_id"]


def test_an_indexed_document_is_described(make, contract_pdf):
    client, container, h = make()
    doc_id = upload(client, h, contract_pdf)
    container.worker.run_until_empty()
    doc = client.get(f"/v1/documents/{doc_id}", headers=h).json()
    assert doc["status"] == "ready" and doc["summary"]
    assert len(doc["suggested_questions"]) == 3 and doc["keywords"]
    listed = client.get("/v1/documents", headers=h).json()["items"][0]
    assert listed["summary"] == doc["summary"], "the list carries the description too"


def test_a_failing_description_never_blocks_the_upload_and_can_be_regenerated(make, contract_pdf):
    state = {"fail": True}

    def light(messages):
        if state["fail"]:
            raise RuntimeError("small model unavailable")
        return json.dumps({"summary": "Un contrat de maintenance.", "keywords": ["contrat", " ", "maintenance"],
                           "suggested_questions": ["Quel est le préavis ?"] * 5})

    client, container, h = make(ScriptedLLM(light))
    doc_id = upload(client, h, contract_pdf)
    container.worker.run_until_empty()
    doc = client.get(f"/v1/documents/{doc_id}", headers=h).json()
    assert doc["status"] == "ready" and doc["summary"] is None

    state["fail"] = False
    r = client.post(f"/v1/documents/{doc_id}/describe", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "Un contrat de maintenance."
    assert body["keywords"] == ["contrat", "maintenance"], "blank keywords are dropped"
    assert len(body["suggested_questions"]) == 3, "capped at three"


def test_describe_is_private_and_needs_a_ready_document(make, contract_pdf):
    client, container, h = make()
    bob = _make_user(container, "bob@example.com")
    doc_id = upload(client, h, contract_pdf)
    assert client.post(f"/v1/documents/{doc_id}/describe", headers=h).status_code == 409, "still pending"
    container.worker.run_until_empty()
    assert client.post(f"/v1/documents/{doc_id}/describe", headers=bob).status_code == 404
