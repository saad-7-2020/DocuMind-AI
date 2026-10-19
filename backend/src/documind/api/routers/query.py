from __future__ import annotations

from fastapi import APIRouter

from documind.api.deps import ContainerDep, UserDep
from documind.api.query_response import build_query_response
from documind.api.schemas import QueryRequest, QueryResponse
from documind.domain.errors import BadRequest, Forbidden
from documind.domain.models import SearchFilters

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, container: ContainerDep, user: UserDep) -> QueryResponse:
    if user.kind == "demo":
        raise Forbidden("Demo accounts use chats.")
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
    return build_query_response(result, body.debug)
