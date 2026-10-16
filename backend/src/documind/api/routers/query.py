from __future__ import annotations

from fastapi import APIRouter

from documind.api.deps import ContainerDep, UserDep
from documind.api.schemas import (
    CitationOut,
    Diagnostics,
    ModelInfo,
    QueryRequest,
    QueryResponse,
    RetrievedOut,
    Usage,
)
from documind.domain.errors import BadRequest
from documind.domain.models import SearchFilters

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, container: ContainerDep, user: UserDep) -> QueryResponse:
    settings = container.settings
    question = body.question.strip()
    if not question:
        raise BadRequest("Question is empty.")
    if len(question) > settings.max_question_chars:
        raise BadRequest(f"Question is longer than {settings.max_question_chars} characters.")
    if body.retrieval.mode != "dense" or body.retrieval.rerank:
        raise BadRequest("Only mode='dense' without rerank is available until Phase 3.")
    # The request can narrow server limits, never raise them.
    top_k = min(body.retrieval.top_k or settings.context_max_chunks, settings.max_top_k)

    filters = SearchFilters(owner_id=user.id, document_ids=body.filters.document_ids)
    result = container.pipeline.run(question, filters, top_k)
    g = result.generated

    diagnostics = None
    if body.debug:
        in_context = {s.chunk.chunk_id for s in g.sources}
        diagnostics = Diagnostics(
            dense=[
                RetrievedOut(rank=i + 1, chunk_id=c.chunk_id, document_id=c.document_id, filename=c.filename,
                             page_start=c.page_start, page_end=c.page_end, score=c.score,
                             in_context=c.chunk_id in in_context)
                for i, c in enumerate(result.retrieved)
            ],
            citations_dropped=g.citations_dropped,
            llm_calls=g.llm_calls,
        )

    return QueryResponse(
        query_id=result.query_id,
        answer=g.answer,
        abstained=g.abstained,
        abstention_reason=g.abstention_reason,
        citations=[CitationOut.model_validate(c, from_attributes=True) for c in g.citations],
        usage=Usage(input_tokens=g.input_tokens, output_tokens=g.output_tokens),
        latency_ms=result.latency_ms,
        model=ModelInfo(embedder=result.config["embedder"], llm=g.llm_model,
                        prompt_version=result.config["prompt_version"]),
        diagnostics=diagnostics,
    )
