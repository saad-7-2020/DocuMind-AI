"""Query pipeline: question → retrieve → build context → generate → map citations (§5).

Phase 2 is dense-only. Phase 3 adds keyword search, RRF fusion, reranking,
quote validation, the evidence gates and query logging.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from documind.domain.models import RetrievedChunk, SearchFilters
from documind.generation.answer import AnswerService, GeneratedAnswer
from documind.generation.prompts import PROMPT_VERSION
from documind.retrieval.base import Retriever


@dataclass
class QueryResult:
    query_id: uuid.UUID
    generated: GeneratedAnswer
    retrieved: list[RetrievedChunk]
    latency_ms: dict[str, int]
    config: dict = field(default_factory=dict)


class QueryPipeline:
    def __init__(self, retriever: Retriever, answers: AnswerService, embedder_id: str) -> None:
        self.retriever = retriever
        self.answers = answers
        self.embedder_id = embedder_id

    def run(self, question: str, filters: SearchFilters, top_k: int,
            history: list[dict[str, str]] | None = None) -> QueryResult:
        t0 = time.perf_counter()
        retrieved = self.retriever.retrieve(question, filters, top_k)
        t1 = time.perf_counter()
        generated = self.answers.answer(question, retrieved, history)
        t2 = time.perf_counter()
        return QueryResult(
            query_id=uuid.uuid4(),
            generated=generated,
            retrieved=retrieved,
            latency_ms={
                "retrieval": int((t1 - t0) * 1000),
                "llm": generated.llm_latency_ms,
                "total": int((t2 - t0) * 1000),
            },
            config={
                "mode": self.retriever.name,
                "top_k": top_k,
                "rerank": False,
                "embedder": self.embedder_id,
                "llm": generated.llm_model,
                "prompt_version": PROMPT_VERSION,
            },
        )
