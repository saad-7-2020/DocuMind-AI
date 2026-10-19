"""Issuing, listing and revoking API keys."""

from __future__ import annotations

import pytest

from documind.auth import create_key, create_user_with_key, list_keys, revoke_key
from documind.db.session import transaction

pytestmark = pytest.mark.integration


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def owner(container):
    with transaction(container.sf) as s:
        _, first = create_user_with_key(s, "owner@example.com")
    return first


def test_a_second_key_works_and_revoking_the_first_locks_only_it_out(client, container, owner):
    with transaction(container.sf) as s:
        second = create_key(s, "owner@example.com")
    assert client.get("/v1/documents", headers=auth(owner)).status_code == 200
    assert client.get("/v1/documents", headers=auth(second)).status_code == 200

    with transaction(container.sf) as s:
        assert revoke_key(s, owner[:8]) == 1
    assert client.get("/v1/documents", headers=auth(owner)).status_code == 401, "revoked key is rejected"
    assert client.get("/v1/documents", headers=auth(second)).status_code == 200, "the new key is unaffected"


def test_listing_shows_only_prefixes_and_status(container, owner):
    with transaction(container.sf) as s:
        create_key(s, "owner@example.com")
        revoke_key(s, owner[:8])
    with container.sf() as s:
        rows = list_keys(s, "owner@example.com")
    assert len(rows) == 2
    assert all(len(prefix) == 8 and prefix.startswith("dm_") for prefix, *_ in rows)
    revoked = {prefix: r for prefix, _, _, r in rows}
    assert revoked[owner[:8]] is not None and sum(r is None for r in revoked.values()) == 1


def test_unknown_prefix_and_unknown_user_are_reported_not_guessed(container, owner):
    with transaction(container.sf) as s:
        assert revoke_key(s, "dm_nothin") == 0
    with pytest.raises(LookupError), transaction(container.sf) as s:
        create_key(s, "nobody@example.com")


def test_an_ambiguous_prefix_is_refused(container, owner):
    from sqlalchemy import text

    with container.engine.begin() as conn:  # force two active keys with the same prefix
        conn.execute(text("""
            INSERT INTO api_keys (user_id, key_prefix, key_hash)
            SELECT user_id, key_prefix, sha256(gen_random_uuid()::text::bytea) FROM api_keys LIMIT 1
        """))
    with pytest.raises(ValueError, match="refusing to guess"), transaction(container.sf) as s:
        revoke_key(s, owner[:8])
