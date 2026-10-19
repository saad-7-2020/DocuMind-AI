"""Demo accounts: self-service sign-up, access codes, throttling, limits, expiry, privacy."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from documind.auth import DEMO_PREFIX
from documind.container import build_container
from tests.conftest import _make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def env(settings):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    made = []

    def _make(**overrides):
        container = build_container(settings.model_copy(update=overrides))
        with container.engine.begin() as conn:
            conn.execute(text("TRUNCATE users, documents, jobs, query_logs, eval_runs, auth_failures CASCADE"))
        client = TestClient(create_app(container))
        client.__enter__()
        made.append((client, container))
        return client, container

    yield _make
    for client, container in made:
        client.__exit__(None, None, None)
        container.close()


def bearer(code: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {code}"}


def demo(client) -> str:
    r = client.post("/v1/demo")
    assert r.status_code == 201, r.text
    return r.json()["access_code"]


def test_demo_signup_returns_a_code_that_works(env):
    client, _ = env()
    body = client.post("/v1/demo").json()
    code = body["access_code"]
    assert code.startswith(DEMO_PREFIX) and len(code) == len(DEMO_PREFIX) + 10
    assert body["limits"]["max_documents"] >= 1 and body["expires_in_days"] >= 1
    me = client.get("/v1/me", headers=bearer(code)).json()
    assert me["kind"] == "demo" and me["expires_at"] and me["usage"]["documents"] == 0


def test_the_code_is_forgiving_about_case_and_spaces(env):
    client, _ = env()
    code = demo(client)
    noisy = f"  {code.upper()}  "
    assert client.get("/v1/me", headers=bearer(noisy)).status_code == 200


def test_two_demo_accounts_cannot_see_each_other(env, tmp_path):
    client, container = env(demo_signups_per_ip_per_day=10)
    a, b = demo(client), demo(client)
    note = tmp_path / "note.txt"
    note.write_text("Le préavis de résiliation est de trente jours.", encoding="utf-8")
    with note.open("rb") as f:
        doc_id = client.post("/v1/documents", headers=bearer(a), files={"file": ("note.txt", f)}).json()["document_id"]
    container.worker.run_until_empty()
    assert client.get(f"/v1/documents/{doc_id}", headers=bearer(b)).status_code == 404
    assert client.get("/v1/documents", headers=bearer(b)).json()["items"] == []


def test_signups_are_limited_per_network(env):
    client, _ = env(demo_signups_per_ip_per_day=2)
    demo(client), demo(client)
    r = client.post("/v1/demo")
    assert r.status_code == 429 and r.json()["code"] == "demo_unavailable"


def test_the_demo_can_be_turned_off_or_full(env):
    client, _ = env(demo_enabled=False)
    assert client.post("/v1/demo").status_code == 429
    client, _ = env(demo_max_active_accounts=1)
    demo(client)
    assert client.post("/v1/demo").status_code == 429


def test_wrong_codes_are_throttled_then_everything_from_that_address_is_blocked(env):
    client, _ = env(auth_max_failures=3)
    good = demo(client)
    for _ in range(3):
        assert client.get("/v1/me", headers=bearer("docu-mindwrongcode")).status_code == 401
    blocked = client.get("/v1/me", headers=bearer("docu-mindwrongcode"))
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many_attempts"
    assert client.get("/v1/me", headers=bearer(good)).status_code == 429, "even the right code waits"


def test_demo_limits_are_enforced(env, tmp_path):
    client, _ = env(demo_max_documents=1, demo_max_conversations=1, demo_max_questions_per_day=1)
    code = demo(client)
    h = bearer(code)
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(f"Contenu du fichier {name}.", encoding="utf-8")
    with (tmp_path / "a.txt").open("rb") as f:
        assert client.post("/v1/documents", headers=h, files={"file": ("a.txt", f)}).status_code == 202
    with (tmp_path / "b.txt").open("rb") as f:
        r = client.post("/v1/documents", headers=h, files={"file": ("b.txt", f)})
    assert r.status_code == 403 and r.json()["code"] == "quota_exceeded"

    chat = client.post("/v1/conversations", headers=h, json={}).json()
    assert client.post("/v1/conversations", headers=h, json={}).status_code == 403
    url = f"/v1/conversations/{chat['id']}/messages"
    assert client.post(url, headers=h, json={"question": "Bonjour"}).status_code == 200
    assert client.post(url, headers=h, json={"question": "Encore"}).status_code == 403


def test_owner_accounts_have_no_limits_and_demo_cannot_use_the_raw_query_api(env):
    client, container = env(demo_max_documents=0)
    owner = _make_user(container, "owner@example.com")
    assert client.get("/v1/me", headers=owner).json()["limits"] is None
    code = demo(client)
    assert client.post("/v1/query", headers=bearer(code), json={"question": "x"}).status_code == 403


def test_idle_demo_accounts_expire_with_their_data(env, tmp_path):
    client, container = env(demo_ttl_days=7)
    stale, fresh = demo(client), demo(client)
    note = tmp_path / "n.txt"
    note.write_text("Un document à effacer.", encoding="utf-8")
    with note.open("rb") as f:
        client.post("/v1/documents", headers=bearer(stale), files={"file": ("n.txt", f)})
    container.worker.run_until_empty()
    with container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET last_active_at = now() - interval '8 days' "
                          "WHERE id = (SELECT user_id FROM api_keys WHERE key_prefix = :p)"),
                     {"p": stale[: len(DEMO_PREFIX) + 5]})
    assert container.accounts.purge_expired() == 1
    assert client.get("/v1/me", headers=bearer(stale)).status_code == 401
    assert client.get("/v1/me", headers=bearer(fresh)).status_code == 200
    with container.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 0


def test_cleanup_endpoint_needs_the_secret(env):
    client, _ = env(cron_secret=SecretStr("s3cret"))
    assert client.get("/internal/cleanup").status_code == 401
    assert client.get("/internal/cleanup", headers=bearer("wrong")).status_code == 401
    r = client.get("/internal/cleanup", headers=bearer("s3cret"))
    assert r.status_code == 200 and r.json() == {"purged": 0}
    client, _ = env()  # no secret configured: the route does not exist
    assert client.get("/internal/cleanup", headers=bearer("anything")).status_code == 404
