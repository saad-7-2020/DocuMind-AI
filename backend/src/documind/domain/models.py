"""Domain value objects shared between pipeline stages. No I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"


class JobKind(StrEnum):
    INGEST = "ingest"
    REINDEX = "reindex"
    DELETE = "delete"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExtractionMethod(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    DOCX = "docx"
    PLAIN = "plain"


MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_TXT = "text/plain"


@dataclass(frozen=True)
class PageText:
    """Text of one physical (PDF) or logical (TXT/DOCX) page, 1-based."""

    page_number: int
    text: str
    method: ExtractionMethod
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class ChunkDraft:
    """A chunk before embedding. Offsets index into the concatenated document text."""

    chunk_index: int
    text: str
    char_start: int
    char_end: int
    page_start: int
    page_end: int
    token_count: int
    section_path: str | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by a retriever, with everything a citation needs."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    page_start: int
    page_end: int
    text: str
    token_count: int
    score: float
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchFilters:
    owner_id: UUID
    document_ids: list[UUID] | None = None
