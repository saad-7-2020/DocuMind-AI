import pytest

from documind.config import Settings


def settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def test_cors_origins_accept_a_plain_comma_separated_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://documind.vercel.app/, http://localhost:5173")
    assert settings().cors_origins == ["https://documind.vercel.app", "http://localhost:5173"]


def test_cors_is_disabled_by_default():
    assert settings().cors_origins == []


def test_embedding_extra_fields_are_read_as_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMBEDDING_QUERY_EXTRA", '{"task": "retrieval.query"}')
    monkeypatch.setenv("EMBEDDING_DOCUMENT_EXTRA", '{"task": "retrieval.passage"}')
    s = settings()
    assert s.embedding_query_extra == {"task": "retrieval.query"}
    assert s.embedding_document_extra == {"task": "retrieval.passage"}


def test_secrets_are_not_shown_in_repr(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "very-secret-service-key")
    monkeypatch.setenv("EMBEDDING_API_KEY", "very-secret-embedding-key")
    monkeypatch.setenv("GROQ_API_KEY", "very-secret-groq-key")
    text = repr(settings())
    assert "very-secret" not in text


def test_supabase_storage_requires_credentials():
    from documind.container import build_blob_store

    with pytest.raises(ValueError, match="SUPABASE_URL"):
        build_blob_store(settings(storage_backend="supabase"))


def test_serverless_settings(monkeypatch: pytest.MonkeyPatch):
    assert settings().inline_jobs is False and settings().db_pool_size == 5
    monkeypatch.setenv("INLINE_JOBS", "true")
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    s = settings()
    assert s.inline_jobs is True and s.db_pool_size == 2


def test_engine_pool_size_and_connect_timeout_follow_the_settings():
    from documind.db.session import make_engine

    engine = make_engine("postgresql+psycopg://u:p@127.0.0.1:1/db", pool_size=2, max_overflow=1)
    assert engine.pool.size() == 2 and engine.pool._max_overflow == 1
    engine.dispose()
