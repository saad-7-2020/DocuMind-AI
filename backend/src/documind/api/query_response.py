"""Build the public QueryResponse from a pipeline result (shared by /v1/query and the chat endpoints)."""

from __future__ import annotations

from documind.api.schemas import CitationOut, Diagnostics, ModelInfo, QueryResponse, RetrievedOut, Usage
from documind.rag.query_pipeline import QueryResult


def build_query_response(result: QueryResult, debug: bool, standalone_question: str | None = None) -> QueryResponse:
    g = result.generated
    diagnostics = None
    if debug:
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
        answer_type=g.answer_type,
        abstained=g.abstained,
        abstention_reason=g.abstention_reason,
        abstention_message=g.abstention_message,
        standalone_question=standalone_question,
        citations=[CitationOut.model_validate(c, from_attributes=True) for c in g.citations],
        usage=Usage(input_tokens=g.input_tokens, output_tokens=g.output_tokens),
        latency_ms=result.latency_ms,
        model=ModelInfo(embedder=result.config["embedder"], llm=g.llm_model,
                        prompt_version=result.config["prompt_version"]),
        diagnostics=diagnostics,
    )
