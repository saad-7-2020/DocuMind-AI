"""Request/response models: the API contract (docs/architecture.md §9)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UploadAccepted(BaseModel):
    document_id: UUID
    job_id: UUID
    status: str


class DocumentSummary(BaseModel):
    id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    page_count: int | None
    created_at: datetime


class DocumentDetail(DocumentSummary):
    title: str | None
    language: str
    ocr_page_count: int
    chunk_count: int
    error_code: str | None
    updated_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    next_cursor: str | None


class PageOut(BaseModel):
    page_number: int
    text: str
    extraction_method: str


class JobAccepted(BaseModel):
    job_id: UUID


class JobOut(BaseModel):
    id: UUID
    kind: str
    status: str
    stage: str | None
    progress: float
    attempts: int
    document_id: UUID | None
    error_code: str | None


class QueryFilters(BaseModel):
    document_ids: list[UUID] | None = Field(default=None, max_length=100)


class RetrievalOptions(BaseModel):
    mode: Literal["dense", "keyword", "hybrid"] = "dense"
    top_k: int | None = Field(default=None, ge=1)
    rerank: bool = False


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    filters: QueryFilters = QueryFilters()
    retrieval: RetrievalOptions = RetrievalOptions()
    debug: bool = False


class CitationOut(BaseModel):
    marker: str
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_start: int
    page_end: int
    quote: str
    score: float


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None  # needs configured prices; never estimated


class ModelInfo(BaseModel):
    embedder: str
    llm: str | None
    prompt_version: str


class RetrievedOut(BaseModel):
    rank: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_start: int
    page_end: int
    score: float
    in_context: bool


class Diagnostics(BaseModel):
    dense: list[RetrievedOut]
    citations_dropped: int
    llm_calls: int


class QueryResponse(BaseModel):
    query_id: UUID
    answer: str | None
    abstained: bool
    abstention_reason: str | None
    citations: list[CitationOut]
    usage: Usage
    latency_ms: dict[str, int]
    model: ModelInfo
    diagnostics: Diagnostics | None = None
