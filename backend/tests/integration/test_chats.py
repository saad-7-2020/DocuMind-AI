"""Chats: create / rename / delete, memory for follow-ups, privacy, document scope, identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from documind.container import build_container
from documind.generation.llm.fake import EchoLightLLM, ScriptedLLM, echo_first_source
from tests.conftest import _make_user

pytestmark = pytest.mark.integration


def typed(answer_type, answer, citations=(), reason=None) -> str:
    return json.dumps({"answer_type": answer_type, "answer": answer, "citations": list(citations),
                       "insufficient_evidence": answer_type == "insufficient", "reason": reason})


@pytest.fixture
def chat_env(settings):
    """(client, container, headers): a real database, fake models you can script."""
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    made = []

    def _make(llm=None, light_llm=None):
        container = build_container(settings, llm=llm or ScriptedLLM(echo_first_source),
                                    light_llm=light_llm or EchoLightLLM())
        with container.engine.begin() as conn:
            conn.execute(text("TRUNCATE users, documents, jobs, query_logs, eval_runs CASCADE"))
        client = TestClient(create_app(container))
        client.__enter__()
        made.append((client, container))
        return client, container, _make_user(container, "chat@example.com")

    yield _make
    for client, container in made:
        client.__exit__(None, None, None)
        container.close()


def upload_and_index(client, container, headers, path: Path) -> str:
    with path.open("rb") as f:
        doc_id = client.post("/v1/documents", headers=headers, files={"file": (path.name, f)}).json()["document_id"]
    container.worker.run_until_empty()
    return doc_id


def new_chat(client, headers, **body) -> dict:
    r = client.post("/v1/conversations", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def send(client, headers, conversation_id, question, **extra):
    return client.post(f"/v1/conversations/{conversation_id}/messages", headers=headers,
                       json={"question": question, **extra})


def test_create_list_rename_and_delete(chat_env):
    client, _, headers = chat_env()
    a, b = new_chat(client, headers), new_chat(client, headers, title="Contrat Altéa")
    assert a["title"] == "" and b["title"] == "Contrat Altéa"
    assert {c["id"] for c in client.get("/v1/conversations", headers=headers).json()} == {a["id"], b["id"]}

    r = client.patch(f"/v1/conversations/{a['id']}", headers=headers, json={"title": "  Mon titre  "})
    assert r.status_code == 200 and r.json()["title"] == "Mon titre"
    assert client.patch(f"/v1/conversations/{a['id']}", headers=headers, json={"title": ""}).status_code == 422

    assert client.delete(f"/v1/conversations/{a['id']}", headers=headers).status_code == 204
    assert client.get(f"/v1/conversations/{a['id']}", headers=headers).status_code == 404
    assert [c["id"] for c in client.get("/v1/conversations", headers=headers).json()] == [b["id"]]


def test_a_message_is_stored_with_its_citations_and_names_the_chat(chat_env, contract_pdf):
    client, container, headers = chat_env()
    upload_and_index(client, container, headers, contract_pdf)
    chat = new_chat(client, headers)

    r = send(client, headers, chat["id"], "Quel est le préavis de résiliation du contrat ?")
    assert r.status_code == 200
    exchange = r.json()
    assert exchange["conversation"]["title"].startswith("Quel est le préavis de résiliation")
    assert exchange["user_message"]["role"] == "user" and exchange["assistant_message"]["role"] == "assistant"
    assert exchange["assistant_message"]["response"]["citations"], "the answer is cited"

    detail = client.get(f"/v1/conversations/{chat['id']}", headers=headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    stored = detail["messages"][1]["response"]
    assert stored["citations"][0]["page_end"] >= 1 and stored["model"]["prompt_version"] == "answer-fr-v3"


def test_follow_up_questions_are_rewritten_using_the_history(chat_env, contract_pdf):
    seen = []

    def light(messages):
        if "Texte du document" in messages[-1]["content"]:  # the document description, not a routing call
            return json.dumps({"summary": "", "keywords": [], "suggested_questions": []})
        seen.append(messages[-1]["content"])
        if "Historique" not in messages[-1]["content"]:
            return json.dumps({"needs_documents": True, "standalone_question": "Quelle est la durée du contrat ?"})
        return json.dumps({"needs_documents": True,
                           "standalone_question": "Quel est le prix annuel de la maintenance ?"})

    main = ScriptedLLM(echo_first_source)
    client, container, headers = chat_env(llm=main, light_llm=ScriptedLLM(light))
    upload_and_index(client, container, headers, contract_pdf)
    chat = new_chat(client, headers)

    first = send(client, headers, chat["id"], "Quelle est la durée du contrat ?").json()
    assert len(seen) == 1 and "Historique" not in seen[0], "the first message is routed without history"
    assert first["assistant_message"]["response"]["standalone_question"] is None

    second = send(client, headers, chat["id"], "Et le prix ?").json()["assistant_message"]["response"]
    assert len(seen) == 2 and "Quelle est la durée du contrat ?" in seen[1]
    assert "Dernier message : Et le prix ?" in seen[1]
    assert second["standalone_question"] == "Quel est le prix annuel de la maintenance ?"
    final_prompt = main.calls[-1][-1]["content"]
    assert "Question : Quel est le prix annuel de la maintenance ?" in final_prompt, "retrieval uses the rewrite"
    assert "Historique récent" in final_prompt


def test_a_failing_rewrite_never_breaks_the_chat(chat_env, contract_pdf):
    def boom(messages):
        raise RuntimeError("small model unavailable")

    client, container, headers = chat_env(light_llm=ScriptedLLM(boom))
    upload_and_index(client, container, headers, contract_pdf)
    chat = new_chat(client, headers)
    send(client, headers, chat["id"], "Quelle est la durée du contrat ?")
    r = send(client, headers, chat["id"], "Et le prix ?")
    assert r.status_code == 200 and r.json()["assistant_message"]["response"]["standalone_question"] is None


def test_the_assistant_can_answer_about_itself_even_with_no_documents(chat_env):
    reply = typed("assistant", "Je suis DocuMind AI, un assistant créé par Saad pour interroger vos documents.")
    client, _, headers = chat_env(llm=ScriptedLLM([reply]))
    chat = new_chat(client, headers)
    r = send(client, headers, chat["id"], "Qui es-tu et qui t'a créé ?").json()["assistant_message"]["response"]
    assert r["answer_type"] == "assistant" and not r["abstained"] and r["citations"] == []
    assert "DocuMind AI" in r["answer"]


def test_an_unanswerable_question_keeps_the_friendly_explanation(chat_env, contract_pdf):
    reply = typed("insufficient", None, reason="Je ne trouve pas cela dans vos documents.")
    client, container, headers = chat_env(llm=ScriptedLLM([reply]))
    upload_and_index(client, container, headers, contract_pdf)
    chat = new_chat(client, headers)
    exchange = send(client, headers, chat["id"], "Qui a gagné la Coupe du monde ?").json()
    r = exchange["assistant_message"]["response"]
    assert r["abstained"] and r["abstention_message"] == "Je ne trouve pas cela dans vos documents."
    assert exchange["assistant_message"]["content"] == "Je ne trouve pas cela dans vos documents."


def test_a_chat_can_be_limited_to_some_documents(chat_env, contract_pdf, tmp_path):
    client, container, headers = chat_env()
    contract_id = upload_and_index(client, container, headers, contract_pdf)
    other = tmp_path / "bail.txt"
    other.write_text("Le préavis de résiliation du bail est de trois mois.", encoding="utf-8")
    other_id = upload_and_index(client, container, headers, other)

    chat = new_chat(client, headers, document_ids=[other_id])
    answer = send(client, headers, chat["id"], "préavis de résiliation").json()["assistant_message"]["response"]
    assert {c["document_id"] for c in answer["citations"]} == {other_id}

    client.patch(f"/v1/conversations/{chat['id']}", headers=headers, json={"clear_scope": True})
    detail = client.get(f"/v1/conversations/{chat['id']}", headers=headers).json()
    assert detail["conversation"]["document_ids"] is None
    assert contract_id != other_id


def test_chats_are_private_to_their_owner(chat_env, contract_pdf):
    client, container, alice = chat_env()
    bob = _make_user(container, "bob@example.com")
    chat = new_chat(client, alice)
    send(client, alice, chat["id"], "Bonjour")

    cid = chat["id"]
    assert client.get(f"/v1/conversations/{cid}", headers=bob).status_code == 404
    assert client.patch(f"/v1/conversations/{cid}", headers=bob, json={"title": "pirate"}).status_code == 404
    assert client.delete(f"/v1/conversations/{cid}", headers=bob).status_code == 404
    assert send(client, bob, cid, "Salut").status_code == 404
    assert client.get("/v1/conversations", headers=bob).json() == []
    assert client.get(f"/v1/conversations/{cid}", headers=alice).status_code == 200


def test_deleting_a_chat_deletes_its_messages(chat_env):
    client, container, headers = chat_env()
    chat = new_chat(client, headers)
    send(client, headers, chat["id"], "Bonjour")
    with container.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM messages")).scalar() == 2
    client.delete(f"/v1/conversations/{chat['id']}", headers=headers)
    with container.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM messages")).scalar() == 0


def test_question_validation(chat_env):
    client, _, headers = chat_env()
    chat = new_chat(client, headers)
    assert send(client, headers, chat["id"], "").status_code == 422
    assert send(client, headers, chat["id"], "x" * 2001).status_code == 400
    assert send(client, headers, chat["id"], "   ").status_code in (400, 422)


def test_a_greeting_is_answered_without_searching_the_documents(chat_env, contract_pdf):
    greeting = typed("smalltalk", "Bonjour ! Ravi de vous voir. Comment puis-je vous aider avec vos documents ?")
    main = ScriptedLLM([greeting])
    client, container, headers = chat_env(llm=main)
    upload_and_index(client, container, headers, contract_pdf)
    chat = new_chat(client, headers)
    r = send(client, headers, chat["id"], "hi").json()["assistant_message"]["response"]
    assert r["answer_type"] == "smalltalk" and r["citations"] == [] and not r["abstained"]
    assert r["latency_ms"]["retrieval"] == 0 and r["diagnostics"] is None
    assert "aucune recherche documentaire" in main.calls[0][-1]["content"]


def test_if_the_router_is_wrong_the_documents_are_searched_after_all(chat_env, contract_pdf):
    def light(messages):
        if "Texte du document" in messages[-1]["content"]:
            return json.dumps({"summary": "", "keywords": [], "suggested_questions": []})
        return json.dumps({"needs_documents": False, "standalone_question": "x"})

    insufficient = typed("insufficient", None, reason="Je ne trouve pas cela dans le message.")
    cited = typed("document", "Le préavis est de trente jours [S1].",
                  [{"source_id": "S1", "quote": "préavis de trente (30) jours"}])
    main = ScriptedLLM([insufficient, cited])
    client, container, headers = chat_env(llm=main, light_llm=ScriptedLLM(light))
    upload_and_index(client, container, headers, contract_pdf)
    chat = new_chat(client, headers)
    exchange = send(client, headers, chat["id"], "Quel est le préavis de résiliation ?").json()
    r = exchange["assistant_message"]["response"]
    assert r["answer_type"] == "document" and r["citations"], "second pass searched and cited"
    assert len(main.calls) == 2


def test_the_assistant_remembers_the_last_five_exchanges(chat_env):
    main = ScriptedLLM([typed("smalltalk", "ok")])
    client, _, headers = chat_env(llm=main)
    chat = new_chat(client, headers)
    for i in range(7):
        send(client, headers, chat["id"], f"message numéro {i}")
    prompt = main.calls[-1][-1]["content"]
    assert "message numéro 5" in prompt and "message numéro 1" in prompt, "the last 5 exchanges are in context"
    assert "message numéro 0" not in prompt, "older ones are not"
