"""Indexing pipeline: blob → extract → clean → chunk → embed → store (§4)."""

from __future__ import annotations

import uuid

import numpy as np
import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from documind.chunking.chunker import RecursiveChunker, chunk_id, join_pages
from documind.db.session import transaction
from documind.db.tables import Chunk, Document, DocumentPage
from documind.domain.errors import NoTextFound
from documind.domain.models import DocumentStatus, PageText
from documind.embedding.base import Embedder
from documind.ingestion.cleaning import clean_pages
from documind.ingestion.extractors import Extractor, extractor_for
from documind.ingestion.jobs import ClaimedJob, JobQueue
from documind.ingestion.storage import BlobStore

log = structlog.get_logger(__name__)

EMBED_PROGRESS_BATCH = 64


class IndexingService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        blob_store: BlobStore,
        extractors: list[Extractor],
        chunker: RecursiveChunker,
        embedder: Embedder,
        queue: JobQueue,
    ) -> None:
        self.sf = session_factory
        self.blobs = blob_store
        self.extractors = extractors
        self.chunker = chunker
        self.embedder = embedder
        self.queue = queue

    # ── ingest / reindex ─────────────────────────────────
    def ingest(self, job: ClaimedJob) -> None:
        assert job.document_id is not None
        with transaction(self.sf) as s:
            doc = s.get(Document, job.document_id)
            if doc is None or doc.status == DocumentStatus.DELETING:
                log.info("ingest_skipped", job_id=str(job.id), reason="document deleted")
                return
            doc.status = DocumentStatus.PROCESSING.value
            mime, storage_key = doc.mime_type, doc.storage_key

        self.queue.set_stage(job.id, "extracting", 0.05)
        pages = extractor_for(mime, self.extractors).extract(self.blobs.path(storage_key))

        self.queue.set_stage(job.id, "cleaning", 0.15)
        pages = clean_pages(pages)
        if not any(p.text for p in pages):
            raise NoTextFound()

        self.queue.set_stage(job.id, "chunking", 0.2)
        drafts = self.chunker.chunk(pages)

        vectors = self._embed([d.text for d in drafts], job)

        self.queue.set_stage(job.id, "storing", 0.95)
        self._store(job, pages, drafts, vectors)

    def _embed(self, texts: list[str], job: ClaimedJob) -> np.ndarray:
        parts = []
        for i in range(0, len(texts), EMBED_PROGRESS_BATCH):
            self.queue.set_stage(job.id, "embedding", 0.25 + 0.7 * i / max(1, len(texts)))
            parts.append(self.embedder.embed_documents(texts[i : i + EMBED_PROGRESS_BATCH]))
        return np.concatenate(parts) if parts else np.zeros((0, self.embedder.dim), np.float32)

    def _store(self, job: ClaimedJob, pages: list[PageText], drafts, vectors: np.ndarray) -> None:
        _, page_offsets = join_pages(pages)
        with transaction(self.sf) as s:
            # Lock the row so a concurrent DELETE can't interleave with our writes.
            doc = s.execute(
                select(Document).where(Document.id == job.document_id).with_for_update()
            ).scalar_one_or_none()
            if doc is None or doc.status == DocumentStatus.DELETING:
                log.info("ingest_discarded", job_id=str(job.id), reason="deleted during processing")
                return
            # Idempotent: a retried or re-run job replaces, never duplicates.
            s.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            s.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
            s.add_all(
                DocumentPage(
                    document_id=doc.id, page_number=p.page_number, text=p.text,
                    extraction_method=p.method.value, ocr_confidence=p.ocr_confidence, char_offset=off,
                )
                for p, off in zip(pages, page_offsets, strict=True)
            )
            s.add_all(
                Chunk(
                    id=chunk_id(doc.id, self.chunker.config_hash, d.chunk_index),
                    document_id=doc.id, owner_id=doc.owner_id, chunk_index=d.chunk_index,
                    page_start=d.page_start, page_end=d.page_end, char_start=d.char_start, char_end=d.char_end,
                    section_path=d.section_path, text=d.text, token_count=d.token_count,
                    chunker_config_hash=self.chunker.config_hash, embedding_model=self.embedder.model_id,
                    embedding=vec,
                )
                for d, vec in zip(drafts, vectors, strict=True)
            )
            doc.status = DocumentStatus.READY.value
            doc.page_count = len(pages)
            doc.error_code = None
        log.info("ingest_done", job_id=str(job.id), document_id=str(job.document_id),
                 pages=len(pages), chunks=len(drafts))

    def mark_failed(self, document_id: uuid.UUID | None, error_code: str) -> None:
        if document_id is None:
            return
        with transaction(self.sf) as s:
            doc = s.get(Document, document_id)
            if doc is not None and doc.status != DocumentStatus.DELETING:
                doc.status = DocumentStatus.FAILED.value
                doc.error_code = error_code

    # ── delete ───────────────────────────────────────────
    def delete(self, job: ClaimedJob) -> None:
        if job.document_id is None:  # already gone
            return
        with transaction(self.sf) as s:
            doc = s.get(Document, job.document_id)
            if doc is None:
                return
            key = doc.storage_key
            s.delete(doc)  # pages and chunks go with it (ON DELETE CASCADE)
            s.flush()
            still_used = s.scalar(select(func.count()).select_from(Document).where(Document.storage_key == key))
        if not still_used:
            self.blobs.delete(key)
        log.info("delete_done", job_id=str(job.id))
