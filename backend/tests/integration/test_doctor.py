"""`documind doctor` against the test database, with fake model providers."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from documind.doctor import run_doctor

pytestmark = pytest.mark.integration


def by_name(checks):
    return {c.name: c for c in checks}


def test_all_checks_pass_with_a_healthy_setup(container):
    checks = by_name(run_doctor(container, container.settings))
    assert [c.ok for c in checks.values()] == [True] * 4, {n: c.detail for n, c in checks.items()}
    assert "pgvector" in checks["Database"].detail and "migrations at 0003" in checks["Database"].detail
    assert "1024-d vectors" in checks["Embeddings"].detail
    assert "upload, download and delete all work" in checks["Storage"].detail


def test_skip_flags_leave_out_the_paid_calls(container):
    names = [c.name for c in run_doctor(container, container.settings, skip_embeddings=True, skip_llm=True)]
    assert names == ["Database", "Storage"]


def test_storage_failure_is_reported_with_a_hint(container):
    class BrokenStore:
        def put(self, *args, **kwargs):
            from documind.domain.errors import StorageError

            raise StorageError("upload: storage returned HTTP 403")

        @contextmanager
        def open_local(self, key):
            yield None

        def delete(self, key):
            pass

    container.blobs = BrokenStore()
    settings = container.settings.model_copy(update={"storage_backend": "supabase"})
    check = by_name(run_doctor(container, settings, skip_embeddings=True, skip_llm=True))["Storage"]
    assert not check.ok and "HTTP 403" in check.detail
    assert "PRIVATE bucket" in check.hint


def test_database_failure_gives_the_ipv6_hint_and_never_prints_the_password(container):
    from documind.container import build_container

    secret = "s3cretpw"
    settings = container.settings.model_copy(update={
        "database_url": f"postgresql+psycopg://postgres:{secret}@db.abcdefgh.supabase.co:5432/postgres?connect_timeout=2",
    })
    broken = build_container(settings)
    try:
        check = by_name(run_doctor(broken, settings, skip_embeddings=True, skip_llm=True))["Database"]
    finally:
        broken.close()
    assert not check.ok
    assert "Session pooler" in check.hint
    assert secret not in check.detail and secret not in check.hint
