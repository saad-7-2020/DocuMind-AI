"""Dense (embedding) retrieval with pgvector (§5.1)."""

from __future__ import annotations

import structlog
from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from documind.db.session import transaction
from documind.domain.models import RetrievedChunk, SearchFilters
from documind.embedding.base import Embedder

log = structlog.get_logger(__name__)

# Filters live *inside* the SQL, so another user's chunk can never enter the candidate list.
# Only fixed fragments are concatenated; every value is a bound parameter.
_BASE_SQL = """
SELECT c.id, c.document_id, d.filename, c.chunk_index, c.page_start, c.page_end,
       c.text, c.token_count, 1 - (c.embedding <=> :qvec) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE c.owner_id = :owner_id
  AND d.status = 'ready'
  AND c.embedding_model = :model
"""
_DOC_FILTER = "  AND c.document_id = ANY(:document_ids)\n"
_ORDER = "ORDER BY c.embedding <=> :qvec\nLIMIT :k"


class DenseRetriever:
    name = "dense"

    def __init__(self, session_factory: sessionmaker[Session], embedder: Embedder) -> None:
        self.sf = session_factory
        self.embedder = embedder

    def retrieve(self, question: str, filters: SearchFilters, k: int) -> list[RetrievedChunk]:
        qvec = self.embedder.embed_query(question)
        sql = _BASE_SQL + (_DOC_FILTER if filters.document_ids else "") + _ORDER
        stmt = text(sql).bindparams(bindparam("qvec", type_=Vector(self.embedder.dim)))
        params: dict = {"qvec": qvec, "owner_id": filters.owner_id, "model": self.embedder.model_id, "k": k}
        if filters.document_ids:
            stmt = stmt.bindparams(bindparam("document_ids", type_=ARRAY(UUID(as_uuid=True))))
            params["document_ids"] = list(filters.document_ids)

        with transaction(self.sf) as s:
            # HNSW is approximate and filters are applied after the index scan; with a selective
            # filter it could return fewer than k rows. Iterative scans (pgvector >= 0.8) keep
            # scanning until k rows pass the filter. relaxed_order may return rows slightly
            # out of order, so we re-sort below.
            # Needs pgvector >= 0.8. On an older server the SET fails: a savepoint keeps that from
            # aborting the whole transaction, and the search simply runs without iterative scans.
            try:
                with s.begin_nested():
                    s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            except DBAPIError:
                log.warning("hnsw_iterative_scan_unavailable")
            rows = s.execute(stmt, params).all()

        chunks = [
            RetrievedChunk(
                chunk_id=r.id, document_id=r.document_id, filename=r.filename, chunk_index=r.chunk_index,
                page_start=r.page_start, page_end=r.page_end, text=r.text, token_count=r.token_count,
                score=float(r.score),
            )
            for r in rows
        ]
        return sorted(chunks, key=lambda c: c.score, reverse=True)
