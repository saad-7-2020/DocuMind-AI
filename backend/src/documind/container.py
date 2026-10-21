"""Composition root: the only place that turns config into concrete classes.

Every other module depends on interfaces (Embedder, LLMProvider, Retriever, â€¦).
Tests build a container with fakes by passing `embedder=` / `llm=`.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from documind.accounts.service import AccountService
from documind.chat.router import QuestionRouter
from documind.chat.service import ChatService
from documind.chunking.chunker import ChunkerConfig, RecursiveChunker
from documind.config import Settings
from documind.db.session import make_engine, make_session_factory
from documind.embedding.base import Embedder
from documind.generation.answer import AnswerService
from documind.generation.llm.base import LLMProvider
from documind.generation.prompts import Identity
from documind.indexing.describe import DocumentDescriber
from documind.indexing.service import IndexingService
from documind.ingestion.extractors import PdfExtractor, TxtExtractor
from documind.ingestion.jobs import JobQueue
from documind.ingestion.storage import BlobStore, LocalBlobStore, SupabaseBlobStore
from documind.rag.query_pipeline import QueryPipeline
from documind.retrieval.dense import DenseRetriever
from documind.worker.runner import Worker

log = structlog.get_logger(__name__)


@dataclass
class Container:
    settings: Settings
    engine: Engine
    sf: sessionmaker[Session]
    blobs: BlobStore
    embedder: Embedder
    llm: LLMProvider
    light_llm: LLMProvider
    queue: JobQueue
    indexing: IndexingService
    pipeline: QueryPipeline
    chats: ChatService
    accounts: AccountService
    worker: Worker

    def close(self) -> None:
        self.engine.dispose()

    def run_pending_jobs(self, max_jobs: int = 5) -> int:
        """In inline mode (serverless hosting), process queued jobs now, inside the current request.

        Never raises: a failure here must not fail the request that triggered it. The job stays queued
        (or is re-queued with backoff) and is picked up again by the next call.
        """
        if not self.settings.inline_jobs:
            return 0
        try:
            return self.worker.run_until_empty(max_jobs=max_jobs)
        except Exception as e:
            log.warning("inline_jobs_failed", error_type=type(e).__name__)
            return 0


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "fake":
        from documind.embedding.fake import HashEmbedder

        return HashEmbedder(settings.embedding_dim)
    if settings.embedder == "openai_compat":
        from documind.embedding.openai_compat import OpenAICompatEmbedder

        return OpenAICompatEmbedder(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key.get_secret_value(),
            model=settings.embedding_model,
            dim=settings.embedding_dim,
            batch_size=settings.embed_batch_size,
            query_extra=settings.embedding_query_extra,
            document_extra=settings.embedding_document_extra,
            send_dimensions=settings.embedding_send_dimensions,
            api_style=settings.embedding_api_style,
            timeout_s=settings.embedding_timeout_s,
            max_retries=settings.embedding_max_retries,
            chars_per_token=settings.embedding_chars_per_token,
        )
    from documind.embedding.sentence_transformers import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(
        settings.embedding_model, settings.embedding_dim, settings.model_device, settings.embed_batch_size,
        cache_dir=str(settings.model_cache_dir) if settings.model_cache_dir else None,
    )


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        from documind.generation.llm.fake import ScriptedLLM, echo_first_source

        return ScriptedLLM(echo_first_source)
    from documind.generation.llm.openai_compat import OpenAICompatLLM

    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.groq_api_key.get_secret_value(),
        model=settings.llm_model,
        structured_mode=settings.llm_structured_mode,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        reasoning_effort=settings.llm_reasoning_effort,
    )


def build_light_llm(settings: Settings) -> LLMProvider:
    """The small, fast model for light jobs (rewriting follow-ups, describing documents)."""
    if settings.llm_provider == "fake":
        from documind.generation.llm.fake import EchoLightLLM

        return EchoLightLLM()
    from documind.generation.llm.openai_compat import OpenAICompatLLM

    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.groq_api_key.get_secret_value(),
        model=settings.llm_light_model,
        structured_mode="json_schema",
        reasoning_effort="low",
        temperature=0.0,
        max_output_tokens=700,
        timeout_s=min(settings.llm_timeout_s, 25.0),
        max_retries=2,
    )


def build_blob_store(settings: Settings) -> BlobStore:
    if settings.storage_backend == "supabase":
        if not settings.supabase_url or not settings.supabase_secret_key.get_secret_value():
            raise ValueError("STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SECRET_KEY")
        return SupabaseBlobStore(
            settings.supabase_url, settings.supabase_secret_key.get_secret_value(), settings.supabase_bucket
        )
    return LocalBlobStore(settings.storage_dir)


def build_container(
    settings: Settings, *, embedder: Embedder | None = None, llm: LLMProvider | None = None,
    light_llm: LLMProvider | None = None,
) -> Container:
    engine = make_engine(settings.database_url, settings.db_pool_size, settings.db_max_overflow)
    sf = make_session_factory(engine)
    blobs = build_blob_store(settings)
    embedder = embedder or build_embedder(settings)
    llm = llm or build_llm(settings)
    light_llm = light_llm or build_light_llm(settings)
    queue = JobQueue(sf)
    chunker = RecursiveChunker(
        ChunkerConfig(settings.chunk_max_tokens, settings.chunk_overlap_tokens),
        count_tokens=embedder.count_tokens,
        tokenizer_id=embedder.tokenizer_id,
    )
    indexing = IndexingService(
        sf, blobs, [PdfExtractor(settings.max_pages), TxtExtractor()], chunker, embedder, queue,
        DocumentDescriber(light_llm, sf),
    )
    identity = Identity(settings.app_name, settings.creator_name, settings.creator_url, settings.creator_bio)
    answers = AnswerService(llm, settings.context_max_chunks, settings.context_max_tokens, identity)
    pipeline = QueryPipeline(DenseRetriever(sf, embedder), answers, embedder.model_id)
    chats = ChatService(sf, pipeline, QuestionRouter(light_llm), settings)
    accounts = AccountService(sf, blobs, settings)
    worker = Worker(queue, indexing, settings.job_timeout_s, settings.worker_poll_interval_s)
    return Container(settings, engine, sf, blobs, embedder, llm, light_llm, queue, indexing, pipeline, chats,
                     accounts, worker)
