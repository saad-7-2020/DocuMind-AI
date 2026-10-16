"""Composition root: the only place that turns config into concrete classes.

Every other module depends on interfaces (Embedder, LLMProvider, Retriever, …).
Tests build a container with fakes by passing `embedder=` / `llm=`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from documind.chunking.chunker import ChunkerConfig, RecursiveChunker
from documind.config import Settings
from documind.db.session import make_engine, make_session_factory
from documind.embedding.base import Embedder
from documind.generation.answer import AnswerService
from documind.generation.llm.base import LLMProvider
from documind.indexing.service import IndexingService
from documind.ingestion.extractors import PdfExtractor, TxtExtractor
from documind.ingestion.jobs import JobQueue
from documind.ingestion.storage import LocalBlobStore
from documind.rag.query_pipeline import QueryPipeline
from documind.retrieval.dense import DenseRetriever
from documind.worker.runner import Worker


@dataclass
class Container:
    settings: Settings
    engine: Engine
    sf: sessionmaker[Session]
    blobs: LocalBlobStore
    embedder: Embedder
    llm: LLMProvider
    queue: JobQueue
    indexing: IndexingService
    pipeline: QueryPipeline
    worker: Worker

    def close(self) -> None:
        self.engine.dispose()


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "fake":
        from documind.embedding.fake import HashEmbedder

        return HashEmbedder(settings.embedding_dim)
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


def build_container(
    settings: Settings, *, embedder: Embedder | None = None, llm: LLMProvider | None = None
) -> Container:
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    blobs = LocalBlobStore(settings.storage_dir)
    embedder = embedder or build_embedder(settings)
    llm = llm or build_llm(settings)
    queue = JobQueue(sf)
    chunker = RecursiveChunker(
        ChunkerConfig(settings.chunk_max_tokens, settings.chunk_overlap_tokens),
        count_tokens=embedder.count_tokens,
        tokenizer_id=embedder.tokenizer_id,
    )
    indexing = IndexingService(
        sf, blobs, [PdfExtractor(settings.max_pages), TxtExtractor()], chunker, embedder, queue
    )
    answers = AnswerService(llm, settings.context_max_chunks, settings.context_max_tokens)
    pipeline = QueryPipeline(DenseRetriever(sf, embedder), answers, embedder.model_id)
    worker = Worker(queue, indexing, settings.job_timeout_s, settings.worker_poll_interval_s)
    return Container(settings, engine, sf, blobs, embedder, llm, queue, indexing, pipeline, worker)
