"""`documind doctor`: check that the configured services actually work, before deploying.

Run it with the same environment variables the server will use (production values set in your own
terminal). It never prints secrets: only hosts, ports, user names and model names.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url

from documind.config import Settings
from documind.container import Container
from documind.domain.errors import DocuMindError
from documind.generation.prompts import ANSWER_SCHEMA


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str | None = None


def _first_line(e: BaseException, limit: int = 220) -> str:
    lines = str(e).strip().splitlines() or [type(e).__name__]
    return f"{type(e).__name__}: {lines[0][:limit]}"


def _database_hint(settings: Settings, error: str) -> str | None:
    url = make_url(settings.database_url)
    host = url.host or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return ("This is Supabase's direct connection, which is IPv6-only. Use the Session pooler string "
                "(Connect -> Direct tab -> Session pooler: host aws-...pooler.supabase.com, port 5432).")
    if url.port == 6543:
        return "Port 6543 is the transaction pooler (no prepared statements). Use session mode, port 5432."
    if "Tenant or user not found" in error:
        return "With the pooler the user must be postgres.<project-ref>, not plain 'postgres'."
    if "password authentication failed" in error:
        return "Wrong password, or special characters in it are not URL-encoded (@ -> %40, / -> %2F, : -> %3A)."
    if "timeout" in error.lower() or "timed out" in error.lower():
        return "Connection timed out: check the host, and that you use the Session pooler (IPv4)."
    return None


def check_database(container: Container, settings: Settings) -> Check:
    url = make_url(settings.database_url)
    where = f"{url.host}:{url.port} as {url.username}"
    try:
        with container.engine.connect() as conn:
            server = conn.execute(text("SHOW server_version")).scalar_one()
            vector = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
            available = conn.execute(
                text("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar()
            unaccent = conn.execute(
                text("SELECT count(*) FROM pg_available_extensions WHERE name = 'unaccent'")
            ).scalar()
            try:
                migration = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:
                conn.rollback()
                migration = None
    except Exception as e:
        message = _first_line(e)
        return Check("Database", False, f"{where}: {message}", _database_hint(settings, str(e)))
    if vector is None and available is None:
        return Check("Database", False, f"{where}: PostgreSQL {server}, but pgvector is not available",
                     "Enable it: Supabase -> Database -> Extensions -> vector.")
    parts = [
        f"PostgreSQL {server}",
        f"pgvector {vector or available + ' (installed by the first migration)'}",
        f"migrations at {migration}" if migration else "migrations not applied yet (they run at start-up)",
        "unaccent available" if unaccent else "no unaccent (French search will keep accents)",
        where,
    ]
    return Check("Database", True, " | ".join(parts))


def check_storage(container: Container, settings: Settings) -> Check:
    """Upload, read back and delete a small object: exercises the same code the app uses."""
    payload = os.urandom(64)
    sha = hashlib.sha256(payload).hexdigest()
    spool = settings.storage_dir / "tmp"
    spool.mkdir(parents=True, exist_ok=True)
    source = spool / f"doctor-{sha[:12]}.bin"
    source.write_bytes(payload)
    label = settings.storage_backend
    if settings.storage_backend == "supabase":
        label += f" (bucket '{settings.supabase_bucket}')"
    key = None
    try:
        key = container.blobs.put(sha, source, "application/octet-stream")
        with container.blobs.open_local(key) as local:
            if local.read_bytes() != payload:
                return Check("Storage", False, f"{label}: the file read back differs from what was uploaded")
        container.blobs.delete(key)
        key = None
    except Exception as e:
        hint = None
        if settings.storage_backend == "supabase":
            hint = ("Check SUPABASE_URL, SUPABASE_SECRET_KEY, and that a PRIVATE bucket named "
                    f"'{settings.supabase_bucket}' exists (Supabase -> Storage). If you see HTTP 401/403, "
                    "try the legacy service_role key (Settings -> API Keys -> Legacy).")
        detail = e.detail if isinstance(e, DocuMindError) else _first_line(e)
        return Check("Storage", False, f"{label}: {detail}", hint)
    finally:
        source.unlink(missing_ok=True)
        if key is not None:
            try:
                container.blobs.delete(key)
            except Exception:
                pass
    return Check("Storage", True, f"{label}: upload, download and delete all work")


def check_embeddings(container: Container, settings: Settings) -> Check:
    emb = container.embedder
    started = time.perf_counter()
    try:
        query = emb.embed_query("Quel est le préavis de résiliation ?")
        docs = emb.embed_documents(["Le préavis est de trente jours.", "Le prix annuel est de 12 000 euros."])
    except Exception as e:
        detail = e.detail if isinstance(e, DocuMindError) else _first_line(e)
        return Check("Embeddings", False, f"{emb.model_id}: {detail}",
                     "Check EMBEDDING_API_KEY, EMBEDDING_BASE_URL (for Cloudflare it must contain your account id) and "
                     "EMBEDDING_MODEL. Cloudflare's free allowance is per day (resets 00:00 UTC): errors after "
                     "heavy use may just mean it is used up. If the response format is the problem, try "
                     "EMBEDDING_API_STYLE=cloudflare with base URL .../accounts/<id>/ai.")
    ms = int((time.perf_counter() - started) * 1000)
    if query.shape != (settings.embedding_dim,) or docs.shape != (2, settings.embedding_dim):
        return Check("Embeddings", False, f"{emb.model_id}: unexpected vector shape {query.shape}")
    similar = float(docs[0] @ query) > float(docs[1] @ query)
    note = "relevant sentence ranks first" if similar else "WARNING: ranking looks off for a known pair"
    return Check("Embeddings", True, f"{emb.model_id}: {settings.embedding_dim}-d vectors in {ms} ms | {note}")


def check_llm(container: Container, settings: Settings) -> Check:
    started = time.perf_counter()
    try:
        result = container.llm.generate(
            [
                {"role": "system", "content": 'Réponds uniquement par un objet JSON: {"answer": "OK", "citations": [], '
                                              '"insufficient_evidence": false, "reason": null}'},
                {"role": "user", "content": "Test de connexion."},
            ],
            "grounded_answer",
            ANSWER_SCHEMA,
        )
        json.loads(result.content)
    except Exception as e:
        detail = e.detail if isinstance(e, DocuMindError) else _first_line(e)
        return Check("LLM", False, f"{container.llm.model_id}: {detail}",
                     "Check GROQ_API_KEY and LLM_MODEL (Groq may have retired the model).")
    ms = int((time.perf_counter() - started) * 1000)
    return Check("LLM", True, f"{result.model}: valid structured answer in {ms} ms "
                              f"({result.input_tokens} -> {result.output_tokens} tokens)")


def run_doctor(container: Container, settings: Settings, *, skip_embeddings: bool = False,
               skip_llm: bool = False) -> list[Check]:
    steps: list[Callable[[Container, Settings], Check]] = [check_database, check_storage]
    if not skip_embeddings:
        steps.append(check_embeddings)
    if not skip_llm:
        steps.append(check_llm)
    return [step(container, settings) for step in steps]
