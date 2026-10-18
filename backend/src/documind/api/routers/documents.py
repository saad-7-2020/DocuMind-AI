"""Document management. Every query is scoped to the caller's owner_id, and another
user's document returns 404 (not 403), so the API doesn't reveal that it exists."""

from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from documind.api.deps import ContainerDep, UserDep
from documind.api.schemas import (
    DocumentDetail,
    DocumentList,
    DocumentSummary,
    JobAccepted,
    PageOut,
    UploadAccepted,
)
from documind.db.session import transaction
from documind.db.tables import Chunk, Document, DocumentPage
from documind.domain.errors import BadRequest, Conflict, DuplicateDocument, FileTooLarge, NotFound
from documind.domain.models import DocumentStatus, JobKind
from documind.ingestion.jobs import JobQueue
from documind.ingestion.validation import spool_upload

router = APIRouter(prefix="/v1/documents", tags=["documents"])

_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f]")
MULTIPART_OVERHEAD = 64 * 1024


def _display_name(raw: str | None) -> str:
    """Filenames are display-only. Keep the base name, drop control characters, cap the length."""
    name = re.split(r"[\\/]", raw or "")[-1]
    name = _UNSAFE_NAME_CHARS.sub("", name).strip() or "document"
    return name[:255]


def _owned_document(s: Session, owner_id: uuid.UUID, document_id: uuid.UUID, lock: bool = False) -> Document:
    stmt = select(Document).where(Document.id == document_id, Document.owner_id == owner_id)
    if lock:
        stmt = stmt.with_for_update()
    doc = s.scalar(stmt)
    if doc is None:
        raise NotFound("Document not found.")
    return doc


@router.post("", status_code=202, response_model=UploadAccepted)
def upload_document(
    request: Request,
    container: ContainerDep,
    user: UserDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
) -> UploadAccepted:
    settings = container.settings
    # Cheap early rejection. The real limit is enforced while streaming (spool_upload).
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + MULTIPART_OVERHEAD:
        raise FileTooLarge(f"Maximum upload size is {settings.max_upload_bytes} bytes.")

    tmp_dir = settings.storage_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    spooled = spool_upload(file.file, settings.max_upload_bytes, tmp_dir)
    try:
        try:
            with transaction(container.sf) as s:
                existing = s.scalar(
                    select(Document.id).where(Document.owner_id == user.id, Document.sha256 == spooled.sha256)
                )
                if existing is not None:
                    raise DuplicateDocument(existing_document_id=str(existing))
                key = container.blobs.put(spooled.sha256, spooled.path, spooled.mime_type)
                doc = Document(
                    id=uuid.uuid4(), owner_id=user.id, filename=_display_name(file.filename),
                    mime_type=spooled.mime_type, size_bytes=spooled.size_bytes, sha256=spooled.sha256,
                    storage_key=key, title=title, status=DocumentStatus.PENDING.value,
                )
                s.add(doc)
                s.flush()
                job = JobQueue.enqueue(s, user.id, doc.id, JobKind.INGEST)
        except IntegrityError:
            # Two identical uploads raced; the unique (owner_id, sha256) constraint picked a winner.
            with container.sf() as s:
                existing = s.scalar(
                    select(Document.id).where(Document.owner_id == user.id, Document.sha256 == spooled.sha256)
                )
            raise DuplicateDocument(existing_document_id=str(existing)) from None
    finally:
        spooled.path.unlink(missing_ok=True)
    container.run_pending_jobs()  # serverless mode: index now; otherwise the worker picks the job up
    return UploadAccepted(document_id=doc.id, job_id=job.id, status=doc.status)


def _encode_cursor(created_at: datetime, doc_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{doc_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, did = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), uuid.UUID(did)
    except Exception:
        raise BadRequest("Invalid cursor.") from None


@router.get("", response_model=DocumentList)
def list_documents(
    container: ContainerDep,
    user: UserDep,
    status: DocumentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> DocumentList:
    stmt = select(Document).where(Document.owner_id == user.id)
    if status is not None:
        stmt = stmt.where(Document.status == status.value)
    if cursor:
        created_at, doc_id = _decode_cursor(cursor)
        stmt = stmt.where(tuple_(Document.created_at, Document.id) < tuple_(created_at, doc_id))
    stmt = stmt.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
    with container.sf() as s:
        docs = list(s.scalars(stmt))
    next_cursor = _encode_cursor(docs[limit - 1].created_at, docs[limit - 1].id) if len(docs) > limit else None
    return DocumentList(
        items=[DocumentSummary.model_validate(d, from_attributes=True) for d in docs[:limit]],
        next_cursor=next_cursor,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, container: ContainerDep, user: UserDep) -> DocumentDetail:
    with container.sf() as s:
        doc = _owned_document(s, user.id, document_id)
        chunk_count = s.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)) or 0
    return DocumentDetail.model_validate({**_attrs(doc), "chunk_count": chunk_count})


def _attrs(doc: Document) -> dict:
    return {c.key: getattr(doc, c.key) for c in Document.__mapper__.column_attrs}


@router.get("/{document_id}/pages/{page_number}", response_model=PageOut)
def get_page(document_id: uuid.UUID, page_number: int, container: ContainerDep, user: UserDep) -> PageOut:
    with container.sf() as s:
        _owned_document(s, user.id, document_id)
        page = s.get(DocumentPage, (document_id, page_number))
        if page is None:
            raise NotFound("Page not found.")
        return PageOut(page_number=page.page_number, text=page.text, extraction_method=page.extraction_method)


@router.delete("/{document_id}", status_code=202, response_model=JobAccepted)
def delete_document(document_id: uuid.UUID, container: ContainerDep, user: UserDep) -> JobAccepted:
    with transaction(container.sf) as s:
        doc = _owned_document(s, user.id, document_id, lock=True)
        if doc.status == DocumentStatus.DELETING:
            raise Conflict("Document is already being deleted.")
        # Retrieval only searches status='ready', so the document stops being citable now,
        # before the worker physically removes it.
        doc.status = DocumentStatus.DELETING.value
        job = JobQueue.enqueue(s, user.id, doc.id, JobKind.DELETE)
    container.run_pending_jobs()
    return JobAccepted(job_id=job.id)


@router.post("/{document_id}/reindex", status_code=202, response_model=JobAccepted)
def reindex_document(document_id: uuid.UUID, container: ContainerDep, user: UserDep) -> JobAccepted:
    with transaction(container.sf) as s:
        doc = _owned_document(s, user.id, document_id, lock=True)
        if doc.status not in (DocumentStatus.READY, DocumentStatus.FAILED):
            raise Conflict(f"Document is {doc.status}; wait until it is ready or failed.")
        doc.status = DocumentStatus.PENDING.value
        job = JobQueue.enqueue(s, user.id, doc.id, JobKind.REINDEX)
    container.run_pending_jobs()
    return JobAccepted(job_id=job.id)
