"""Shared fixtures.

Unit tests need nothing. Integration tests (marked `integration`) use the Postgres
test database from docker compose and run with fakes only: no network, no GPU.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import create_engine, text

from documind.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://documind:documind@localhost:5433/documind_test"
)

CONTRACT_PAGES = [
    "Contrat de prestation de services\n\n"
    "Article 1 - Objet. Le présent contrat a pour objet la maintenance du logiciel DocuGest version 4.2. "
    "Le prestataire assure la correction des anomalies et la mise à jour des composants.",
    "Article 2 - Durée. Le contrat est conclu pour une durée de trois ans à compter de sa signature. "
    "Il est renouvelable par tacite reconduction.\n\n"
    "Article 3 - Prix. Le prix annuel de la maintenance est fixé à 12 000 euros hors taxes.",
    "Article 7 - Résiliation. Chacune des parties peut résilier le contrat moyennant un préavis "
    "de trente (30) jours, notifié par lettre recommandée avec accusé de réception.",
]


def make_pdf(path: Path, pages: list[str], encrypt: bool = False) -> Path:
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(page.rect + (50, 50, -50, -50), body, fontsize=11, fontname="helv")
    kwargs = {}
    if encrypt:
        kwargs = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "user"}
    doc.save(path, **kwargs)
    doc.close()
    return path


@pytest.fixture
def contract_pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "contrat.pdf", CONTRACT_PAGES)


# ── Integration fixtures ────────────────────────────────

@pytest.fixture(scope="session")
def migrated_db_url() -> str:
    engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"test database unavailable ({type(e).__name__}); run: docker compose up -d db")
    finally:
        engine.dispose()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DB_URL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return TEST_DB_URL


@pytest.fixture
def settings(migrated_db_url: str, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=migrated_db_url,
        storage_dir=tmp_path / "blobs",
        max_upload_bytes=200_000,
        embedder="fake",
        llm_provider="fake",
        chunk_max_tokens=40,
        chunk_overlap_tokens=8,
        context_max_chunks=4,
    )


@pytest.fixture
def container(settings: Settings) -> Iterator:
    from documind.container import build_container

    c = build_container(settings)
    with c.engine.begin() as conn:
        conn.execute(text("TRUNCATE users, documents, jobs, query_logs, eval_runs CASCADE"))
    yield c
    c.close()


@pytest.fixture
def client(container):
    from fastapi.testclient import TestClient

    from documind.api.app import create_app

    with TestClient(create_app(container)) as tc:
        yield tc


def _make_user(container, email: str) -> dict[str, str]:
    from documind.auth import create_user_with_key
    from documind.db.session import transaction

    with transaction(container.sf) as s:
        _, key = create_user_with_key(s, email)
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def alice(container) -> dict[str, str]:
    return _make_user(container, "alice@example.com")


@pytest.fixture
def bob(container) -> dict[str, str]:
    return _make_user(container, "bob@example.com")
